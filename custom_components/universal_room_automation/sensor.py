"""Sensor platform for Universal Room Automation."""
#
# Universal Room Automation vv5.62.2
# Build: 2026-01-04
# File: sensor.py
# v3.3.1.3: Fixed PersonLikelyNextRoomSensor/PersonCurrentPathSensor __init__ signature
# v3.3.1.2: Fixed missing Optional and AggregationEntity imports
# v3.2.9: No changes (zone fixes in aggregation.py, fan fixes in automation.py)
# v3.2.8.3: Added person_coordinator subscriptions for real-time room sensor updates
# v3.2.8.2: DevicesSensor updated to count multi-domain auto/manual devices
# v3.2.8.1: Added PersonTrackingStatusSensor for room-level diagnostic tracking
# v3.2.8: PersonLocationSensor architectural fix - active state listeners
# v3.2.6: Renamed occupant sensors for clarity:
#   - "Current Occupants" → "Identified People"
#   - "Occupant Count" → "Identified People Count"
#   - "Last Occupant" → "Last Identified Person"
#   - "Last Occupant Time" → "Last Identified Time"
# v3.2.6: Added LastAutomationTimeSensor and PersonCoordinatorDiagnosticSensor
#
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfTemperature,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
    PERCENTAGE,
    LIGHT_LUX,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

# B-LOW-2 fix-up: HousePolicySensor imports hoisted from async_added_to_hass.
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect as _hs_async_dispatcher_connect,
)
from .domain_coordinators.signals import SIGNAL_HOUSE_POLICY_UPDATE

from .const import (
    DOMAIN,
    ICON_TEMPERATURE,
    ICON_HUMIDITY,
    ICON_ILLUMINANCE,
    ICON_TIMEOUT,
    ICON_POWER,
    ICON_ENERGY,
    ICON_COST,
    ICON_DEVICES,
    ICON_PREDICTION,
    ICON_PRECONDITIONING,
    ICON_COMFORT,
    ICON_EFFICIENCY,
    ICON_PATTERN,
    ICON_ANOMALY,
    ICON_CONFIG_STATUS,
    ICON_DIAGNOSTIC,
    ICON_LAST_TRIGGER,
    ICON_LAST_ACTION,
    STATE_TEMPERATURE,
    STATE_HUMIDITY,
    STATE_ILLUMINANCE,
    STATE_TIMEOUT_REMAINING,
    STATE_POWER_CURRENT,
    STATE_ENERGY_TODAY,
    STATE_ENERGY_COST_TODAY,
    STATE_ENERGY_MONTHLY,
    STATE_ENERGY_COST_MONTHLY,
    STATE_ENERGY_WEEKLY,
    STATE_ENERGY_COST_WEEKLY,
    STATE_COST_PER_HOUR,
    STATE_LIGHTS_ON_COUNT,
    STATE_FANS_ON_COUNT,
    STATE_SWITCHES_ON_COUNT,
    STATE_COVERS_OPEN_COUNT,
    STATE_COVERS_POSITION_AVG,
    STATE_NEXT_OCCUPANCY_TIME,
    STATE_OCCUPANCY_PCT_7D,
    STATE_PRECOOL_START_TIME,
    STATE_PREHEAT_START_TIME,
    STATE_PRECOOL_LEAD_MINUTES,
    STATE_PREHEAT_LEAD_MINUTES,
    STATE_OCCUPANCY_CONFIDENCE,
    STATE_COMFORT_SCORE,
    STATE_ENERGY_EFFICIENCY_SCORE,
    STATE_OCCUPIED,
    STATE_TIME_SINCE_MOTION,
    STATE_TIME_SINCE_OCCUPIED,
    CONF_TEMPERATURE_SENSOR,
    # v4.7.16 D2: signal inventory sensor reads these to derive has_*
    CONF_MOTION_SENSORS,
    CONF_MMWAVE_SENSORS,
    CONF_SCANNER_AREAS,
    CONF_AREA_ID,
    CONF_DISABLE_CAMERA_PRESENCE,
    DEFAULT_DISABLE_CAMERA_PRESENCE,
    CONF_ELECTRICITY_RATE,
    DEFAULT_ELECTRICITY_RATE,
    ATTR_CONFIDENCE,
    ATTR_BASED_ON,
    CONF_AI_RULES,
    CONF_AUTOMATION_CHAINS,
)
from .coordinator import UniversalRoomCoordinator
from .entity import UniversalRoomEntity
from .aggregation import AggregationEntity, _get_room_coordinators
from .domain_coordinators.energy_billing import _get_effective_rate_kwh

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation sensors."""
    from .const import (
        CONF_ENTRY_TYPE, ENTRY_TYPE_INTEGRATION, ENTRY_TYPE_ZONE,
        ENTRY_TYPE_ZONE_MANAGER, ENTRY_TYPE_COORDINATOR_MANAGER,
    )

    # Check if this is an integration entry (aggregation sensors)
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
        # Call the comprehensive aggregation sensor setup function
        from .aggregation import async_setup_aggregation_sensors
        await async_setup_aggregation_sensors(hass, entry, async_add_entities)

        # v3.5.0: Add census sensors for integration entry
        census_sensors = [
            URAPersonsInHouseSensor(hass, entry),
            URAIdentifiedPersonsInHouseSensor(hass, entry),
            URAUnidentifiedPersonsInHouseSensor(hass, entry),
            URAPersonsOnPropertySensor(hass, entry),
            URATotalPersonsOnPropertySensor(hass, entry),
            # Disabled by default (diagnostics)
            URACensusConfidenceSensor(hass, entry),
            URACensusValidationAgeSensor(hass, entry),
            # v3.5.1: Perimeter alert status (disabled by default)
            PerimeterAlertStatusSensor(hass, entry),
            # v3.5.2: Warehoused sensors — entry/exit counts and unidentified persons
            PersonsEnteredTodaySensor(hass, entry),
            PersonsExitedTodaySensor(hass, entry),
            LastPersonEntrySensor(hass, entry),
            LastPersonExitSensor(hass, entry),
            UnidentifiedPersonsSensor(hass, entry),
            # build/exterior-track: exterior-track census counters + diagnostic
            ExteriorPersonTracksActiveSensor(hass, entry),
            ExteriorVehicleTracksActiveSensor(hass, entry),
            ExteriorAnimalTracksActiveSensor(hass, entry),
            ExteriorUnidentifiedPersonsSensor(hass, entry),
            ExteriorOpenTracksDiagnosticSensor(hass, entry),
            # v3.6.0-c1: House state on integration device
            IntegrationHouseStateSensor(hass, entry),
            # v3.6.21: Music following health sensor
            MusicFollowingHealthSensor(hass, entry),
            # v5.8.0 D2.12: house-wide reconcile-on-return roll-up
            ReconcileHealthSensor(hass, entry),
        ]
        async_add_entities(census_sensors)

        return

    # v3.6.0: Zone Manager entry - set up ALL zone sensors under this entry
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
        from .aggregation import async_setup_zone_manager_sensors
        await async_setup_zone_manager_sensors(hass, entry, async_add_entities)
        return

    # v3.6.0: Coordinator Manager entry - set up coordinator sensors under this entry
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
        # v4.6.13 review fix C.M1: single source of truth for UI coordinator list.
        from .domain_coordinators.coordinator_telemetry_const import (
            UI_COORDINATORS as _UI_COORDINATORS,
        )
        coordinator_sensors = [
            CoordinatorManagerSensor(hass, entry),
            # Hierarchical Memory MVP Stage 1 — live write-volume watch.
            URAMemoryStatusSensor(hass, entry),
            # House-State Rung 2a (v5.39.0): CM-device house-policy diagnostic
            # surface (INV-1/INV-3).
            HousePolicySensor(hass, entry),
            # v5.36.0 D1: house-level stuck-signal watchdog aggregator.
            URAStuckSignalWatchdogSensor(hass, entry),
            HouseStateSensor(hass, entry),
            CoordinatorSummarySensor(hass, entry),
            # v3.6.0-c1: Presence Coordinator sensors
            PresenceHouseStateSensor(hass, entry),
            HouseStateConfidenceSensor(hass, entry),
            # v4.7.15 D5: Input-agreement confidence (distinct from state confidence).
            SignalConsensusConfidenceSensor(hass, entry),
            PresenceAnomalySensor(hass, entry),
            PresenceComplianceSensor(hass, entry),
            # build/pc-observability: attribute-to-sensor promotions +
            # diagnostic COPY sensor (disabled by default). Additive only.
            PresenceCensusCountSensor(hass, entry),
            PresenceWakeBlockedTicksSensor(hass, entry),
            PresenceWakeBackstopFiresSensor(hass, entry),
            PresenceArrivingRearmSuppressedSensor(hass, entry),
            PresenceArrivingRearmBypassedSensor(hass, entry),
            PresenceDiagnosticSensor(hass, entry),
            # v4.6.9 D1: Routine awareness next-state prediction
            PresenceNextStateSensor(hass, entry),
            # v3.6.0-c2: Safety Coordinator sensors
            SafetyStatusSensor(hass, entry),
            SafetyActiveHazardsSensor(hass, entry),
            SafetyAffectedRoomsSensor(hass, entry),
            SafetyDiagnosticsSensor(hass, entry),
            SafetyAnomalySensor(hass, entry),
            SafetyComplianceSensor(hass, entry),
            # v3.6.0-c3: Security Coordinator sensors
            SecurityArmedStateSensor(hass, entry),
            SecurityLastEntrySensor(hass, entry),
            SecurityAnomalySensor(hass, entry),
            SecurityComplianceSensor(hass, entry),
            SecurityOpenEntriesSensor(hass, entry),
            SecurityLastLockSweepSensor(hass, entry),
            SecurityExpectedArrivalsSensor(hass, entry),
            # v4.6.9 D2: Locks + cameras roll-up aggregator
            SecurityAggregatorSensor(hass, entry),
            # v4.6.9 D3: Energy Coordinator decision stream timeline
            EnergyRecentDecisionsSensor(hass, entry),
            # v3.6.27: Music Following Coordinator sensors
            MusicFollowingAnomalySensor(hass, entry),
            MusicFollowingTransfersTodaySensor(hass, entry),
            MusicFollowingActiveRoomsSensor(hass, entry),
            MusicFollowingLastTransferSensor(hass, entry),
            # v3.6.29: Notification Manager sensors
            NMLastNotificationSensor(hass, entry),
            NMNotificationsTodaySensor(hass, entry),
            NMCooldownRemainingSensor(hass, entry),
            NMChannelStatusSensor(hass, entry),
            NMTriggerSensor(hass, entry),
            NMAnomalySensor(hass, entry),
            NMDeliveryRateSensor(hass, entry),
            NMDiagnosticsSensor(hass, entry),
            NMInboundTodaySensor(hass, entry),
            # v3.7.0-E1: Energy Coordinator sensors
            EnergyTOUPeriodSensor(hass, entry),
            EnergyTOURateSensor(hass, entry),
            EnergyTOUSeasonSensor(hass, entry),
            EnergyBatteryStrategySensor(hass, entry),
            # Session B1 — EVSE drain-precedence state machine observability.
            EnergyDrainPrecedenceStateSensor(hass, entry),
            # v5.5.1 D6: dedicated inclement-weather observability entity
            InclementStateSensor(hass, entry),
            EnergySolarDayClassSensor(hass, entry),
            # v4.7.x Cycle A: WeatherProviderManager sensors
            WeatherActiveProviderSensor(hass, entry),
            WeatherApparentForecastHighSensor(hass, entry),
            # v4.7.1 Cycle B: Dynamic Preset global sensors
            DynamicPresetOverridesAppliedSensor(hass, entry),
            # v4.7.1 fix-up D4: HVAC active preset overrides diagnostic sensor
            HVACActivePresetOverridesSensor(hass, entry),
            # v3.7.0-E2: Pool + EV sensors
            EnergyPoolOptimizationSensor(hass, entry),
            EnergyEVChargingStatusSensor(hass, entry),
            # v3.7.0-E3: Circuit + Generator sensors
            EnergyCircuitAnomalySensor(hass, entry),
            EnergyGeneratorStatusSensor(hass, entry),
            # v3.7.0-E4: Billing + Cost sensors
            EnergyCoordCostTodaySensor(hass, entry),
            EnergyCostCycleSensor(hass, entry),
            EnergyPredictedBillSensor(hass, entry),
            # v4.3.0 D4: Arbitrage savings tracking
            EnergyArbitrageSavingsTodaySensor(hass, entry),
            EnergyArbitrageSavingsCycleSensor(hass, entry),
            EnergyArbitrageSavingsTotalSensor(hass, entry),
            # Energy Savings Unification (cycle #7): additive display family
            EnergySavingsPeakAvoidanceTodaySensor(hass, entry),
            EnergySavingsPeakAvoidanceBillingCycleSensor(hass, entry),
            EnergySavingsPeakAvoidanceLifetimeSensor(hass, entry),
            EnergySavingsTotalTodaySensor(hass, entry),
            EnergySavingsTotalBillingCycleSensor(hass, entry),
            EnergySavingsTotalLifetimeSensor(hass, entry),
            EnergyKwhAvoidedTodaySensor(hass, entry),
            EnergyKwhAvoidedBillingCycleSensor(hass, entry),
            EnergyKwhAvoidedLifetimeSensor(hass, entry),
            EnergyCurrentRateSensor(hass, entry),
            EnergyDeliveryRateSensor(hass, entry),
            EnergyImportTodaySensor(hass, entry),
            EnergyExportTodaySensor(hass, entry),
            # v3.7.0-E5: Forecast sensors
            EnergyForecastTodaySensor(hass, entry),
            EnergyForecastedImportSensor(hass, entry),
            EnergyForecastedConsumptionSensor(hass, entry),
            EnergyBatteryFullTimeSensor(hass, entry),
            EnergyForecastAccuracySensor(hass, entry),
            # v3.7.0-E6: Situation + Constraint sensors
            EnergySituationSensor(hass, entry),
            EnergyHVACConstraintSensor(hass, entry),
            # v3.9.0-E6: Battery decision + Load shedding sensors
            EnergyBatteryDecisionSensor(hass, entry),
            EnergyLoadSheddingSensor(hass, entry),
            # v3.7.7: Consumption + EV monitoring sensors
            EnergyTotalConsumptionSensor(hass, entry),
            EnergyNetConsumptionSensor(hass, entry),
            EnergyEVChargeRateASensor(hass, entry),
            EnergyEVChargeRateBSensor(hass, entry),
            # v3.8.0-H1: HVAC Coordinator sensors
            HVACModeSensor(hass, entry),
            HVACAnomalySensor(hass, entry),
            HVACComplianceSensor(hass, entry),
            HVACOverrideFrequencySensor(hass, entry),
            HVACPreCoolLikelihoodSensor(hass, entry),
            HVACComfortRiskSensor(hass, entry),
            # v4.5.12 D8: 5 house-wide AC ramp-down impact sensors
            HVACACNudgesTodaySensor(hass, entry),
            HVACACResetsTodaySensor(hass, entry),
            HVACACKwhAvoidedTodaySensor(hass, entry),
            HVACACKwhAvoidedTotalSensor(hass, entry),
            HVACACFalsePositiveRateSensor(hass, entry),
            # PLANNING_hvac_kwh_avoided_savings D1+D2: billing-cycle kWh +
            # standalone $ savings family (rough estimate; NOT summed into
            # EC energy_savings_total_*).
            HVACACKwhAvoidedBillingCycleSensor(hass, entry),
            HVACACRampSavingsTodaySensor(hass, entry),
            HVACACRampSavingsBillingCycleSensor(hass, entry),
            HVACACRampSavingsLifetimeSensor(hass, entry),
            # v3.9.0: HVAC transparency sensors
            HVACArresterStateSensor(hass, entry),
            # v3.17.0: Zone Intelligence sensor
            HVACZoneIntelligenceSensor(hass, entry),
            # v3.18.6: Pre-Arrival diagnostic sensor
            HVACPreArrivalDiagnosticSensor(hass, entry),
            # v3.21.1 Cycle E D2-D6: New diagnostic sensors
            HVACArresterStatusSensor(hass, entry),
            NMAlertStateSensor(hass, entry),
            EnergyEnvoyStatusSensor(hass, entry),
            SafetyActiveCooldownsSensor(hass, entry),
            # v4.6.11 D4.8: Safety events summary (last 24h from activity log)
            SafetyEventsSummarySensor(hass, entry),
            # v4.6.9 D5: Safety recent-events ring buffer (last 20 events, newest first)
            SafetyRecentEventsSensor(hass, entry),
            SecurityAuthorizedGuestsSensor(hass, entry),
            # Activity Log sensor
            URALastActivitySensor(hass, entry),
            # v4.0.0-B1: Bayesian Predictor sensors
            BayesianDataQualitySensor(hass, entry),
            # v4.0.0-B2: Prediction accuracy sensor (enabled by default)
            BayesianPredictionAccuracySensor(hass, entry),
            # v4.2.10: Memory diagnostic sensors
            URAMemoryUsageSensor(hass, entry),
            URAMemoryDeltaSensor(hass, entry),
            # v4.6.3 D12: Recent anomalies house-level sensor
            URARecentAnomaliesSensor(hass, entry),
            # v4.6.10 D2: Setup duration diagnostic sensor
            URASetupDurationSensor(hass, entry),
            # v4.6.13 D1-D3, D5: Per-UI-coordinator telemetry sensors (20 sensors).
            # Review C C.M1 fix: import UI_COORDINATORS from the const file so a
            # future 6th coordinator only needs adding to one place.
            *(
                CoordinatorDecisionsTodaySensor(hass, entry, uc)
                for uc in _UI_COORDINATORS
            ),
            *(
                CoordinatorOverrideFrequencySensor(hass, entry, uc)
                for uc in _UI_COORDINATORS
            ),
            *(
                CoordinatorComplianceRateSensor(hass, entry, uc)
                for uc in _UI_COORDINATORS
            ),
            *(
                CoordinatorLastDecisionSensor(hass, entry, uc)
                for uc in _UI_COORDINATORS
            ),
            # v4.6.13 D4: URA SQLite DB size sensor (includes WAL + SHM)
            URADBSizeSensor(hass, entry),
        ]
        # v3.8.0-H1: Add per-zone HVAC sensors dynamically
        # v4.5.13.1: Use canonical-zone helper for thermostat-keyed dedup
        # (Bug Class #36 prevention). Two URA home zones sharing a single
        # thermostat now collapse into one HVAC zone with merged name, so
        # we don't create parallel sets of D7 sensors pointing at the same
        # physical AC. Helper lives in domain_coordinators/hvac_zones.py
        # to keep dedup semantics aligned with ZoneManager.async_discover_zones.
        from .domain_coordinators.hvac_zones import iter_canonical_hvac_zones
        for _z in iter_canonical_hvac_zones(hass):
            zone_id = _z["zone_id"]
            _zname = _z["zone_name"]
            _thermostat = _z["climate_entity"]
            coordinator_sensors.append(
                HVACZoneStatusSensor(hass, entry, zone_id)
            )
            coordinator_sensors.append(
                HVACZonePresetSensor(hass, entry, zone_id)
            )
            # v4.7.1 Cycle B: per-zone dynamic preset sensors
            coordinator_sensors.append(
                DynamicPresetActiveBucketSensor(hass, entry, zone_id, _zname)
            )
            coordinator_sensors.append(
                DynamicPresetRangeSensor(hass, entry, zone_id, _zname)
            )
            # v4.5.12 D7: per-zone AC ramp-down sensors (3 per zone)
            coordinator_sensors.append(
                HVACACRampStateSensor(
                    hass, entry, zone_id, _zname, _thermostat,
                )
            )
            coordinator_sensors.append(
                HVACACRampLastActionSensor(
                    hass, entry, zone_id, _zname, _thermostat,
                )
            )
            coordinator_sensors.append(
                HVACACRampKwhRateSensor(
                    hass, entry, zone_id, _zname, _thermostat,
                )
            )
            # v4.7.8 D5: per-canonical-zone egress state-machine sensor.
            coordinator_sensors.append(
                HVACZoneEgressStateSensor(hass, entry, zone_id, _zname)
            )
        # v4.7.8 D5: single global "paused zones" rollup sensor on HVAC Coordinator.
        coordinator_sensors.append(HVACEgressPausedZonesSensor(hass, entry))
        # v4.6.0 D4/D5 accuracy sensors + v4.6.2 D5 routine_status sensors
        # are registered via aggregation.async_setup_aggregation_sensors
        # (Integration entry), NOT here in the CM entry path — they bind to
        # the CM device via _cm_device_info() but live alongside the other
        # per-person aggregate sensors. Single registration site avoids
        # unique_id collisions on restart.

        # v4.7.34 Phase 1 D7: Optimization Coordinator sensors.
        coordinator_sensors.extend([
            OptimizerStatusSensor(hass, entry),
            OptimizerFindingsSensor(hass, entry),
            # v5.4 D2a — plain-English reasoning sensor (ONE new entity
            # in the cycle; D2b/D2c/D2d are attrs on existing sensors).
            OptimizerReasoningSensor(hass, entry),
            OptimizerRoomHealthSensor(hass, entry),
        ])

        async_add_entities(coordinator_sensors)
        return

    # v3.3.5.6: Legacy zone entry - no longer creates sensors (migrated to Zone Manager)
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
        return

    # Room entry - normal sensor setup
    coordinator: UniversalRoomCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    # === ENVIRONMENTAL (Always Visible) ===
    entities = [
        TemperatureSensor(coordinator),
        HumiditySensor(coordinator),
        IlluminanceSensor(coordinator),
        # v4.7.34 Phase 1 D7: per-room optimization health sensor.
        # Registers with placeholder state so Bug Class #5 (block setup
        # on first eval) does not fire; populates on the first
        # OptimizationCoordinator cycle.
        RoomOptimizationHealthSensor(coordinator),
    ]
    
    # === OCCUPANCY (Always Visible) ===
    entities.extend([
        OccupancyTimeoutSensor(coordinator),
    ])
    
    # === v3.2.0: PERSON TRACKING (Optional) ===
    # ALWAYS create these sensors - they handle missing coordinator gracefully
    # Fixes issue where rooms created before person_coordinator initialization
    # didn't get person sensors (v3.2.2.5 fix)
    entities.extend([
        CurrentOccupantsSensor(coordinator),
        OccupantCountSensor(coordinator),
        LastOccupantSensor(coordinator),
        LastOccupantTimeSensor(coordinator),
        # v3.2.8.1: Room-level person tracking diagnostic sensor
        PersonTrackingStatusSensor(coordinator),
    ])
    
    # === ENERGY - CURRENT (Always Visible) ===
    entities.extend([
        PowerCurrentSensor(coordinator),
        EnergyTodaySensor(coordinator),
        EnergyCostTodaySensor(coordinator),
    ])
    
    # === ENERGY - TRACKING (Optional) ===
    entities.extend([
        EnergyWeeklySensor(coordinator),
        EnergyCostWeeklySensor(coordinator),
        EnergyMonthlySensor(coordinator),
        EnergyCostMonthlySensor(coordinator),
        CostPerHourSensor(coordinator),
    ])
    
    # === DEVICE STATUS (Optional) ===
    entities.extend([
        LightsOnCountSensor(coordinator),
        FansOnCountSensor(coordinator),
        SwitchesOnCountSensor(coordinator),
        CoversOpenCountSensor(coordinator),
        CoversPositionAvgSensor(coordinator),
        DevicesSensor(coordinator),
        DeviceStatusSensor(coordinator),
    ])
    
    # === OCCUPANCY PREDICTIONS (Optional) ===
    # Prediction-sensor kill-list cycle (2026-06):
    # - NextOccupancyInSensor REMOVED — its info is derivable client-side from
    #   the NextOccupancyTimeSensor timestamp; per-minute rewrites caused
    #   ~50k recorder writes/day of churn across ~37 rooms.
    # - PeakOccupancyTimeSensor REMOVED — superseded 1:1 by the per-room
    #   *_bayesian_occupancy_pattern sensor.
    # Orphan unique_ids cleaned up in __init__.py (entry_type INTEGRATION
    # branch) following the v4.7.22 fan-recheck precedent.
    entities.extend([
        NextOccupancyTimeSensor(coordinator),
        OccupancyPercentage7dSensor(coordinator),
    ])
    
    # === HVAC PREDICTIONS (Optional) ===
    entities.extend([
        PrecoolStartTimeSensor(coordinator),
        PrecoolLeadMinutesSensor(coordinator),
        PreheatStartTimeSensor(coordinator),
        PreheatLeadMinutesSensor(coordinator),
    ])
    
    # === COMFORT & EFFICIENCY (Optional) ===
    entities.extend([
        ComfortScoreSensor(coordinator),
        EnergyEfficiencyScoreSensor(coordinator),
    ])
    
    # === TIME TRACKING (Optional) ===
    entities.extend([
        TimeSinceMotionSensor(coordinator),
        TimeSinceOccupiedSensor(coordinator),
        DaysSinceOccupiedSensor(coordinator),
    ])
    
    # === ADVANCED DIAGNOSTICS (Optional) ===
    entities.extend([
        ConfigStatusSensor(coordinator),
        UnavailableEntitiesSensor(coordinator),
        LastAutomationTriggerSensor(coordinator),
        LastAutomationActionSensor(coordinator),
        LastAutomationTimeSensor(coordinator),  # v3.2.6: New sensor
        DatabaseStatusSensor(coordinator),
        AutomationHealthSensor(coordinator),  # v3.6.17: Composite automation health
        RoomReconcileSensor(coordinator),  # v5.8.0 D2.12: reconcile-on-return diagnostic
        RoomSignalInventorySensor(coordinator),  # v4.7.16 D2: BLE tier + signal inventory
        AIAutomationStatusSensor(coordinator),  # v3.12.0 M4: AI rule + chain tracking
    ])

    # === v4.0.0-B1: BAYESIAN OCCUPANCY PREDICTION (Diagnostic) ===
    # v5.2.3: Removed BayesianWeekdayMorningProbSensor +
    # BayesianWeekendEveningProbSensor (hardcoded single-time-bin probes
    # superseded by *_bayesian_occupancy_forecast / *_bayesian_occupancy_pattern).
    entities.extend([
        BayesianOccupancyPatternSensor(coordinator),
    ])

    # === v4.0.0-B2: PREDICTION SENSORS (Diagnostic, disabled) ===
    entities.extend([
        BayesianOccupancyForecastSensor(coordinator),
        OccupancyPercentageTodaySensor(coordinator),
        TimeOccupiedTodaySensor(coordinator),
        TimeUncomfortableTodaySensor(coordinator),
        AvgTimeToComfortSensor(coordinator),
    ])

    # Fan-noise Mode-2: per-room diagnostic sensors. Disabled by default
    # in entity registry — operator enables the rooms they care about.
    # Read FanRecheckManager.get_room_attrs each access.
    entities.extend([
        RoomFanRecheckStateSensor(coordinator),
        RoomFanRecheckLastOutcomeSensor(coordinator),
    ])

    async_add_entities(entities)
    _LOGGER.info(
        "Set up %d sensors for room: %s",
        len(entities),
        entry.data.get("room_name")
    )


# ===================================================================
# PHASE 1: CORE SENSORS
# ===================================================================

class TemperatureSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for room temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = ICON_TEMPERATURE

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "temperature", "Temperature")

    @property
    def native_value(self) -> float | None:
        """Return the temperature."""
        return self.coordinator.data.get(STATE_TEMPERATURE) if self.coordinator.data else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement from source sensor."""
        # v3.2.4 FIX: Merge entry.options with entry.data
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        # Get unit from source sensor to avoid conversion issues (bug fix from v2.0)
        temp_sensor = config.get(CONF_TEMPERATURE_SENSOR)
        if temp_sensor:
            state = self.hass.states.get(temp_sensor)
            if state:
                return state.attributes.get("unit_of_measurement")
        return UnitOfTemperature.CELSIUS  # Fallback

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return (
            self.coordinator.last_update_success and
            (self.coordinator.data and self.coordinator.data.get(STATE_TEMPERATURE)) is not None
        )


class HumiditySensor(UniversalRoomEntity, SensorEntity):
    """Sensor for room humidity."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = ICON_HUMIDITY

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "humidity", "Humidity")

    @property
    def native_value(self) -> float | None:
        """Return the humidity."""
        return self.coordinator.data.get(STATE_HUMIDITY) if self.coordinator.data else None

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return (
            self.coordinator.last_update_success and
            (self.coordinator.data and self.coordinator.data.get(STATE_HUMIDITY)) is not None
        )


class IlluminanceSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for room illuminance."""

    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = LIGHT_LUX
    _attr_icon = ICON_ILLUMINANCE

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "illuminance", "Illuminance")

    @property
    def native_value(self) -> float | None:
        """Return the illuminance."""
        return self.coordinator.data.get(STATE_ILLUMINANCE) if self.coordinator.data else None


class OccupancyTimeoutSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for occupancy timeout remaining."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = ICON_TIMEOUT

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "timeout_remaining", "Occupancy Timeout Remaining")

    @property
    def native_value(self) -> int:
        """Return the timeout remaining in seconds."""
        return self.coordinator.data.get(STATE_TIMEOUT_REMAINING, 0) if self.coordinator.data else 0


# ===================================================================
# PHASE 2: ENERGY INTELLIGENCE
# ===================================================================

class PowerCurrentSensor(UniversalRoomEntity, SensorEntity):
    """Current power consumption sensor."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = ICON_POWER

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "power_current", "Power")

    @property
    def native_value(self) -> float | None:
        """Return the current power consumption."""
        return self.coordinator.data.get(STATE_POWER_CURRENT) if self.coordinator.data else None


class EnergyTodaySensor(UniversalRoomEntity, SensorEntity):
    """Energy consumed today sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = ICON_ENERGY

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_today", "Energy Today")
        self._last_valid_value: float | None = None
        # Fix-up pass C-H1: track the local-date of the most recently
        # accepted value so day-reset detection is DATE-based instead of
        # the magnitude heuristic ``current < 0.1`` (which mis-fires for
        # low-draw rooms that sit <0.1 kWh for hours after the helper
        # normalization landed → recorder churn + decrease leaks).
        self._last_accepted_date = None

    @property
    def native_value(self) -> float | None:
        """Return energy consumed today with monotonic increasing enforcement."""
        if not self.coordinator.data:
            return 0

        current = self.coordinator.data.get(STATE_ENERGY_TODAY, 0)

        # v3.18.3: Round to 4 decimal places (0.1 Wh) to eliminate float jitter
        # that causes HA "entity not strictly increasing" warnings
        if current is not None:
            current = round(current, 4)

        if current is None:
            return current

        # Fix-up pass C-H1: DATE-based day-reset acceptance. A decrease is
        # accepted only when the local date has changed since the last
        # accepted value (genuine midnight rollover); otherwise the
        # monotonic-increasing invariant rejects it and returns the
        # last known good value.
        today = dt_util.now().date()
        if self._last_accepted_date is None:
            # First observation this lifetime.
            self._last_accepted_date = today
            self._last_valid_value = current
            return current

        if self._last_valid_value is not None and current < self._last_valid_value:
            if self._last_accepted_date != today:
                # Genuine new day — accept the decrease (counter reset).
                self._last_accepted_date = today
                self._last_valid_value = current
                return current
            # Same-day decrease — reject (recorder-stat churn fix).
            return self._last_valid_value

        # Monotonic or first-of-day accept path.
        self._last_accepted_date = today
        self._last_valid_value = current
        return current

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose dead-energy-sensor observability flag.

        D4: ``energy_sensors_dead`` is True when ALL of this room's
        configured energy sensors were unavailable on the most recent
        coordinator cycle. STATE_ENERGY_TODAY itself is held as None in
        that case (coordinator-side), which flows safely through
        ``if energy:`` checks downstream. The attribute makes the failure
        mode dashboard-visible without log mining.
        """
        return {
            "energy_sensors_dead": bool(
                getattr(self.coordinator, "_energy_sensors_dead", False)
            ),
        }


class EnergyCostTodaySensor(UniversalRoomEntity, SensorEntity):
    """Energy cost today sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = ICON_COST

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_cost_today", "Energy Cost Today")

    @property
    def native_value(self) -> float | None:
        """Return energy cost today.

        Fix-up pass C1/A-H2: D4 may set STATE_ENERGY_TODAY=None (key
        present, value None) when all configured room energy sensors are
        unavailable. Returning ``None`` here surfaces "unknown cost" to
        downstream consumers (consistent with D4 semantics) instead of
        round(None * rate) → TypeError.
        """
        if not self.coordinator.data:
            return None
        energy = self.coordinator.data.get(STATE_ENERGY_TODAY)
        if energy is None:
            return None
        # v4.6.8: Use TOU-aware rate via helper (EC first, room override, global, default).
        rate, _source = _get_effective_rate_kwh(
            self.coordinator.hass, room_entry=self.coordinator.entry
        )
        return round(energy * rate, 2)


class EnergyMonthlySensor(UniversalRoomEntity, SensorEntity):
    """Monthly energy consumption sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = ICON_ENERGY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_monthly", "Energy Monthly")

    @property
    def native_value(self) -> float | None:
        """Return monthly energy from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_ENERGY_MONTHLY)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class EnergyCostMonthlySensor(UniversalRoomEntity, SensorEntity):
    """Monthly energy cost sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = ICON_COST
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_cost_monthly", "Energy Cost Monthly")

    @property
    def native_value(self) -> float | None:
        """Return monthly energy cost from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_ENERGY_COST_MONTHLY)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class EnergyWeeklySensor(UniversalRoomEntity, SensorEntity):
    """Weekly energy consumption sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = ICON_ENERGY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_weekly", "Energy Weekly")

    @property
    def native_value(self) -> float | None:
        """Return weekly energy from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_ENERGY_WEEKLY)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class EnergyCostWeeklySensor(UniversalRoomEntity, SensorEntity):
    """Weekly energy cost sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_icon = ICON_COST
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_cost_weekly", "Energy Cost Weekly")

    @property
    def native_value(self) -> float | None:
        """Return weekly energy cost from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_ENERGY_COST_WEEKLY)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class CostPerHourSensor(UniversalRoomEntity, SensorEntity):
    """Cost per hour sensor based on current power."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD/h"
    _attr_icon = ICON_COST
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "cost_per_hour", "Cost Per Hour")

    @property
    def native_value(self) -> float | None:
        """Return cost per hour from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_COST_PER_HOUR)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None and
            self.coordinator.data.get(STATE_COST_PER_HOUR) is not None
        )


class LightsOnCountSensor(UniversalRoomEntity, SensorEntity):
    """Count of lights currently on."""

    _attr_icon = "mdi:lightbulb-on"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "lights_on_count", "Lights On")

    @property
    def native_value(self) -> int:
        """Return count of lights on."""
        return self.coordinator.data.get(STATE_LIGHTS_ON_COUNT, 0) if self.coordinator.data else 0


class FansOnCountSensor(UniversalRoomEntity, SensorEntity):
    """Count of fans currently on in the room area.

    D6 (bathroom-exhaust intelligence cycle): renamed display to
    "Comfort Fans On" to disambiguate from the humidity-fan path. Entity
    ID + unique ID unchanged (only `_attr_name`). The underlying count is
    area-derived (coordinator._calculate_device_counts → all `fan.*` in
    the area); humidity fans on switch-domain entities are unaffected.
    """

    _attr_icon = "mdi:fan"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "fans_on_count", "Comfort Fans On")

    @property
    def native_value(self) -> int:
        """Return count of fans on."""
        return self.coordinator.data.get(STATE_FANS_ON_COUNT, 0) if self.coordinator.data else 0


class SwitchesOnCountSensor(UniversalRoomEntity, SensorEntity):
    """Count of switches currently on."""

    _attr_icon = "mdi:light-switch"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "switches_on_count", "Switches On")

    @property
    def native_value(self) -> int:
        """Return count of switches on."""
        return self.coordinator.data.get(STATE_SWITCHES_ON_COUNT, 0) if self.coordinator.data else 0


class CoversOpenCountSensor(UniversalRoomEntity, SensorEntity):
    """Count of covers currently open."""

    _attr_icon = "mdi:window-open"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "covers_open_count", "Covers Open")

    @property
    def native_value(self) -> int:
        """Return count of covers open."""
        return self.coordinator.data.get(STATE_COVERS_OPEN_COUNT, 0) if self.coordinator.data else 0


class CoversPositionAvgSensor(UniversalRoomEntity, SensorEntity):
    """Average position of all covers."""

    _attr_icon = "mdi:window-shutter"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "covers_position_avg", "Covers Position Average")

    @property
    def native_value(self) -> float | None:
        """Return average cover position."""
        return self.coordinator.data.get(STATE_COVERS_POSITION_AVG, 0) if self.coordinator.data else 0


# ===================================================================
# PHASE 3: PREDICTIONS
# ===================================================================

class NextOccupancyTimeSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for predicted next occupancy time.

    device_class=timestamp + tz-aware datetime native_value lets HA frontends
    render the live "in N minutes" countdown client-side without per-minute
    recorder churn. State is written ONLY when the predicted timestamp changes
    (or its tz-aware equivalent changes) — see ``_handle_coordinator_update``.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = ICON_PREDICTION

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "next_occupancy_time", "Next Occupancy Time")
        # Sentinel: a value that can never legitimately equal a datetime/None.
        # Used to force a first write on the first coordinator refresh after
        # entity init so subscribers see a state even if the predictor's first
        # value is None.
        self._last_written: object = object()
        self._last_confidence: object = object()
        self._last_available: object = object()

    def _normalize(self, value: datetime | None) -> datetime | None:
        """Force tz-awareness on the prediction timestamp.

        HA's timestamp device class requires tz-aware values. The sole
        producer today (database get_next_occupancy_prediction) builds from
        ``dt_util.now()`` and is already tz-aware LOCAL, so this branch is
        defensive. A naive datetime is treated as LOCAL via
        ``dt_util.as_utc`` — HA's actual convention (review A-M1/B-B2: a
        naive-as-UTC label here would shift the countdown by the local UTC
        offset, the same bug class the routine-forecaster cycle hit).
        """
        if value is None:
            return None
        if value.tzinfo is None:
            return dt_util.as_utc(value)
        return value

    @property
    def native_value(self) -> datetime | None:
        """Return predicted next occupancy time from coordinator (tz-aware)."""
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get(STATE_NEXT_OCCUPANCY_TIME)
        return self._normalize(raw)

    @property
    def extra_state_attributes(self) -> dict[str, any]:
        """Return additional attributes."""
        attrs = {}
        if self.coordinator.data:
            confidence = self.coordinator.data.get(STATE_OCCUPANCY_CONFIDENCE)
            if confidence is not None:
                # Producer (database get_next_occupancy_prediction) already
                # returns 0-100; the old *100 rendered "8000%" (review A-L3).
                attrs[ATTR_CONFIDENCE] = f"{int(confidence)}%"
        return attrs

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Only write HA state when the predicted timestamp (or confidence) changes.

        Suppresses the per-cycle recorder churn that NextOccupancyInSensor used
        to generate. The countdown UI is now derived client-side from the
        device_class=timestamp value, so we only need to push state on actual
        prediction changes.

        Availability is part of the change tuple (review A-H1/B-B1): this
        override is the entity's ONLY state writer, so an available flip with
        unchanged value/confidence (refresh starts failing while data is
        retained) must still write — otherwise the UI shows a stale timestamp
        as live indefinitely, and recovery is equally unsignaled.
        """
        new_value = self.native_value
        new_confidence = (
            self.coordinator.data.get(STATE_OCCUPANCY_CONFIDENCE)
            if self.coordinator.data
            else None
        )
        new_available = self.available
        if (
            new_value == self._last_written
            and new_confidence == self._last_confidence
            and new_available == self._last_available
        ):
            return
        self._last_written = new_value
        self._last_confidence = new_confidence
        self._last_available = new_available
        self.async_write_ha_state()


class OccupancyPercentage7dSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for 7-day occupancy percentage."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = ICON_PATTERN
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "occupancy_percentage_7d", "Occupancy % (7 days)")

    @property
    def native_value(self) -> float | None:
        """Return 7-day occupancy percentage from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_OCCUPANCY_PCT_7D)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class PrecoolStartTimeSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for when to start precooling."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = ICON_PRECONDITIONING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "precool_start_time", "Precool Start Time")

    @property
    def native_value(self) -> datetime | None:
        """Return precool start time from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_PRECOOL_START_TIME)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class PreheatStartTimeSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for when to start preheating."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = ICON_PRECONDITIONING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "preheat_start_time", "Preheat Start Time")

    @property
    def native_value(self) -> datetime | None:
        """Return preheat start time from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_PREHEAT_START_TIME)

    @property
    def available(self) -> bool:
        """Sensor available if coordinator has data."""
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        )


class PrecoolLeadMinutesSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for precooling lead time."""

    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = ICON_PRECONDITIONING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "precool_lead_minutes", "Precool Lead Minutes")

    @property
    def native_value(self) -> int | None:
        """Return precool lead time from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_PRECOOL_LEAD_MINUTES)

    @property
    def available(self) -> bool:
        """Sensor is always available."""
        return True


class PreheatLeadMinutesSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for preheating lead time."""

    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = ICON_PRECONDITIONING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "preheat_lead_minutes", "Preheat Lead Minutes")

    @property
    def native_value(self) -> int | None:
        """Return preheat lead time from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(STATE_PREHEAT_LEAD_MINUTES)

    @property
    def available(self) -> bool:
        """Sensor is always available."""
        return True


# ===================================================================
# PHASE 4: COMFORT & EFFICIENCY
# ===================================================================

class ComfortScoreSensor(UniversalRoomEntity, SensorEntity):
    """Comfort score based on temperature, humidity, and occupancy.

    Formula: temp_score * 0.4 + humidity_score * 0.3 + occupancy_score * 0.3
    - Temperature: 100 at setpoint, decreases 10 pts per degree F deviation
    - Humidity: 100 at 45%, decreases 2 pts per % deviation
    - Occupancy: 100 when occupied, 50 when unoccupied
    """

    _attr_native_unit_of_measurement = "%"
    _attr_icon = ICON_COMFORT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "comfort_score", "Comfort Score")

    def _get_comfort_range(self) -> tuple[float, float]:
        """Return (low, high) of the per-room comfort range.

        D8 (bathroom-exhaust intelligence cycle): both `CONF_TARGET_TEMP_HEAT`
        (low bound) and `CONF_TARGET_TEMP_COOL` (high bound) are read here.
        Pre-D8 only the high bound was consumed (Bug Class #53 — collected-
        but-not-consumed); this wiring fixes that. Defensive: if low > high
        (validator slipped), normalize via min/max so the scorer never
        crashes on a pathological config.
        """
        from .const import (
            CONF_TARGET_TEMP_COOL,
            CONF_TARGET_TEMP_HEAT,
            DEFAULT_TARGET_TEMP_COOL,
            DEFAULT_TARGET_TEMP_HEAT,
        )
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        low = float(config.get(CONF_TARGET_TEMP_HEAT, DEFAULT_TARGET_TEMP_HEAT))
        high = float(config.get(CONF_TARGET_TEMP_COOL, DEFAULT_TARGET_TEMP_COOL))
        if low > high:
            low, high = min(low, high), max(low, high)
        return low, high

    @staticmethod
    def _comfort_range_temp_score(temp: float, low: float, high: float) -> float:
        """Bi-directional comfort-range temperature score (D8).

        In-range [low, high] → 100. Below low → -10 pts per °F below.
        Above high → -10 pts per °F above. Floored at 0.
        """
        if low <= temp <= high:
            return 100.0
        if temp < low:
            return max(0.0, 100.0 - (low - temp) * 10.0)
        return max(0.0, 100.0 - (temp - high) * 10.0)

    @property
    def native_value(self) -> int | None:
        """Return comfort score 0-100."""
        if not self.coordinator.data:
            return None

        temp = self.coordinator.data.get(STATE_TEMPERATURE)
        humidity = self.coordinator.data.get(STATE_HUMIDITY)

        # Need at least temperature to compute a meaningful score
        if temp is None:
            return None

        low, high = self._get_comfort_range()
        temp_score = self._comfort_range_temp_score(temp, low, high)

        # Humidity component: 100 at 45%, -2 per % deviation
        if humidity is not None:
            humidity_score = max(0, 100 - abs(humidity - 45) * 2)
        else:
            humidity_score = 70

        occupied = self.coordinator.data.get(STATE_OCCUPIED, False)
        occupancy_score = 100 if occupied else 50

        score = temp_score * 0.4 + humidity_score * 0.3 + occupancy_score * 0.3
        return round(score)

    @property
    def extra_state_attributes(self) -> dict:
        """Return scoring breakdown for transparency."""
        if not self.coordinator.data:
            return {}

        temp = self.coordinator.data.get(STATE_TEMPERATURE)
        humidity = self.coordinator.data.get(STATE_HUMIDITY)
        occupied = self.coordinator.data.get(STATE_OCCUPIED, False)

        if temp is None:
            return {}

        low, high = self._get_comfort_range()
        temp_score = self._comfort_range_temp_score(temp, low, high)
        humidity_score = (
            max(0, 100 - abs(humidity - 45) * 2) if humidity is not None else 70
        )
        occupancy_score = 100 if occupied else 50

        return {
            "temperature": temp,
            "comfort_range_low": low,
            "comfort_range_high": high,
            "humidity": humidity,
            "occupied": occupied,
            "temp_score": round(temp_score, 1),
            "humidity_score": round(humidity_score, 1),
            "occupancy_score": occupancy_score,
            "weight_temp": 0.4,
            "weight_humidity": 0.3,
            "weight_occupancy": 0.3,
        }


class EnergyEfficiencyScoreSensor(UniversalRoomEntity, SensorEntity):
    """Energy efficiency score based on HVAC zone performance.

    When HVAC zone data is available:
      Score = 100 - (duty_cycle_pct * 0.5) - (override_count_today * 5)
    Fallback (no HVAC data):
      Within 2 F of target = 90, within 5 F = 70, else 50
    """

    _attr_native_unit_of_measurement = "%"
    _attr_icon = ICON_EFFICIENCY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_efficiency_score", "Energy Efficiency Score")

    def _get_zone_for_room(self) -> tuple[Any, Any] | tuple[None, None]:
        """Find the HVAC zone containing this room, if any.

        Returns (hvac_coordinator, zone_state) or (None, None).
        """
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None, None
        hvac = manager.coordinators.get("hvac")
        if hvac is None or not hasattr(hvac, "zone_manager"):
            return None, None

        room_name = self.coordinator.entry.data.get("room_name", "")
        for zone in hvac.zone_manager.zones.values():
            if room_name in zone.rooms:
                return hvac, zone
        return hvac, None

    def _get_comfort_range(self) -> tuple[float, float]:
        """Return (low, high) of the per-room comfort range.

        D8: reads BOTH CONF_TARGET_TEMP_HEAT (low) and CONF_TARGET_TEMP_COOL
        (high). Defensive normalization on inverted configs.
        """
        from .const import (
            CONF_TARGET_TEMP_COOL,
            CONF_TARGET_TEMP_HEAT,
            DEFAULT_TARGET_TEMP_COOL,
            DEFAULT_TARGET_TEMP_HEAT,
        )
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        low = float(config.get(CONF_TARGET_TEMP_HEAT, DEFAULT_TARGET_TEMP_HEAT))
        high = float(config.get(CONF_TARGET_TEMP_COOL, DEFAULT_TARGET_TEMP_COOL))
        if low > high:
            low, high = min(low, high), max(low, high)
        return low, high

    @staticmethod
    def _comfort_range_deviation(temp: float, low: float, high: float) -> float:
        """Return signed deviation magnitude (in °F) from the comfort range.

        Zero when in-range; positive value when outside. Distance to the
        closer bound.
        """
        if low <= temp <= high:
            return 0.0
        if temp < low:
            return low - temp
        return temp - high

    @property
    def native_value(self) -> int | None:
        """Return efficiency score 0-100."""
        if not self.coordinator.data:
            return None

        hvac, zone = self._get_zone_for_room()

        if zone is not None:
            from .domain_coordinators.hvac_const import DUTY_CYCLE_WINDOW_SECONDS
            if zone.window_start is not None:
                duty_pct = min(
                    zone.runtime_seconds_this_window
                    / DUTY_CYCLE_WINDOW_SECONDS
                    * 100,
                    100.0,
                )
            else:
                duty_pct = 0.0
            override_penalty = zone.override_count_today * 5
            score = 100 - (duty_pct * 0.5) - override_penalty
            return max(0, min(100, round(score)))

        # Fallback (D8): comfort-range proximity. In-range = 90; within 3°F
        # of the closer bound = 70; else 50. Symmetric across both bounds.
        temp = self.coordinator.data.get(STATE_TEMPERATURE)
        if temp is None:
            return None
        low, high = self._get_comfort_range()
        deviation = self._comfort_range_deviation(temp, low, high)
        if deviation == 0.0:
            return 90
        if deviation <= 3:
            return 70
        return 50

    @property
    def extra_state_attributes(self) -> dict:
        """Return scoring breakdown for transparency."""
        if not self.coordinator.data:
            return {}

        attrs: dict[str, Any] = {}
        hvac, zone = self._get_zone_for_room()

        if zone is not None:
            from .domain_coordinators.hvac_const import DUTY_CYCLE_WINDOW_SECONDS
            if zone.window_start is not None:
                duty_pct = min(
                    zone.runtime_seconds_this_window
                    / DUTY_CYCLE_WINDOW_SECONDS
                    * 100,
                    100.0,
                )
            else:
                duty_pct = 0.0
            attrs["scoring_method"] = "hvac_zone"
            attrs["zone_name"] = zone.zone_name
            attrs["duty_cycle_pct"] = round(duty_pct, 1)
            attrs["override_count_today"] = zone.override_count_today
            attrs["duty_penalty"] = round(duty_pct * 0.5, 1)
            attrs["override_penalty"] = zone.override_count_today * 5
        else:
            temp = self.coordinator.data.get(STATE_TEMPERATURE)
            low, high = self._get_comfort_range()
            attrs["scoring_method"] = "comfort_range_proximity"
            attrs["temperature"] = temp
            attrs["comfort_range_low"] = low
            attrs["comfort_range_high"] = high
            if temp is not None:
                attrs["deviation_f"] = round(
                    self._comfort_range_deviation(temp, low, high), 1,
                )

        return attrs


class TimeSinceMotionSensor(UniversalRoomEntity, SensorEntity):
    """Time since last motion detected."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:motion-sensor-off"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "time_since_motion", "Time Since Motion")

    @property
    def native_value(self) -> int | None:
        """Return seconds since last motion."""
        return self.coordinator.data.get(STATE_TIME_SINCE_MOTION) if self.coordinator.data else None


class TimeSinceOccupiedSensor(UniversalRoomEntity, SensorEntity):
    """Time since room was last occupied."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_icon = "mdi:clock-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "time_since_occupied", "Time Since Occupied")

    @property
    def native_value(self) -> float | None:
        """Return hours since last occupied."""
        seconds = self.coordinator.data.get(STATE_TIME_SINCE_OCCUPIED) if self.coordinator.data else None
        if seconds is not None:
            return round(seconds / 3600, 2)  # Convert seconds to hours
        return None


class ConfigStatusSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for configuration health status."""

    _attr_icon = ICON_CONFIG_STATUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "config_status", "Configuration Status")

    @property
    def native_value(self) -> str:
        """Return configuration status."""
        # v3.2.4 FIX: Merge entry.options with entry.data
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        # Check for required sensors
        temp_sensor = config.get(CONF_TEMPERATURE_SENSOR)
        motion_sensors = config.get("motion_sensors", [])
        mmwave_sensors = config.get("presence_sensors", [])
        occupancy_sensors = config.get("occupancy_sensors", [])
        
        if not temp_sensor:
            return "Missing Temperature Sensor"
        if not motion_sensors and not mmwave_sensors and not occupancy_sensors:
            return "Missing Occupancy Sensors"
        
        return "OK"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        # v3.2.4 FIX: Merge entry.options with entry.data
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        return {
            "has_temperature": bool(config.get(CONF_TEMPERATURE_SENSOR)),
            "has_humidity": bool(config.get("humidity_sensor")),
            "has_illuminance": bool(config.get("illuminance_sensor")),
            "has_motion": bool(config.get("motion_sensors")),
            "has_presence": bool(config.get("presence_sensors")),
            "has_occupancy": bool(config.get("occupancy_sensors")),
        }


class UnavailableEntitiesSensor(UniversalRoomEntity, SensorEntity):
    """Sensor listing unavailable entities."""

    _attr_icon = ICON_ANOMALY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "unavailable_entities", "Unavailable Entities")

    # Configured-entity roles, split by category. Inputs degrade DETECTION;
    # actuators degrade ACTUATION — different operational meaning, surfaced
    # separately in the attributes so consumers can treat them differently.
    _SENSOR_LIST_KEYS = ("motion_sensors", "presence_sensors",
                         "occupancy_sensors", "power_sensors")
    _SENSOR_SINGLE_KEYS = ("temperature_sensor", "humidity_sensor",
                           "illuminance_sensor")
    _ACTUATOR_LIST_KEYS = ("lights", "night_lights", "alert_lights",
                           "fans", "humidity_fans", "covers")
    # v5.10.0 D1: room_media_player is an ACTUATOR — a dead speaker means
    # music_following silently no-ops. Surface it in
    # sensor.<room>_unavailable_entities so operators can see it.
    _ACTUATOR_SINGLE_KEYS = ("climate_entity", "room_media_player")

    @property
    def native_value(self) -> int:
        """Return count of unavailable configured entities (inputs + actuators)."""
        eids = self._get_unavailable_entities()
        # NEW (item 15): sensor_dropout episode on empty→non-empty
        # transition. No new detection machinery — hooks the EXISTING
        # unavailable-entities tracking. Dedup gate in log_memory_episode
        # (MED B4) prevents storm bursts. Systemic events (cross-node) are
        # answerable at read time by observer-tier queries.
        try:
            prev = int(self.__dict__.get(
                "_memory_dropout_prev_count", 0,
            ))
        except Exception:  # noqa: BLE001
            prev = 0
        cur = len(eids)
        if prev == 0 and cur > 0:
            try:
                _db = self.coordinator.hass.data.get(DOMAIN, {}).get(
                    "database",
                )
                if _db is not None and hasattr(
                    _db, "log_memory_episode",
                ):
                    _room = getattr(self.coordinator, "room_name", None) or (
                        getattr(self.coordinator, "_room_name", None)
                    )
                    if _room:
                        _slug = _room.lower().replace(
                            " ", "_",
                        ).replace("-", "_")
                        # Best-effort house_state stamp — never blocks.
                        _hs = None
                        try:
                            mgr = self.coordinator.hass.data.get(
                                DOMAIN, {},
                            ).get("coordinator_manager")
                            pres = (
                                getattr(mgr, "coordinators", {}).get(
                                    "presence",
                                )
                                if mgr is not None else None
                            )
                            _hs = (
                                str(getattr(pres, "house_state", None))
                                if pres is not None else None
                            )
                        except Exception:  # noqa: BLE001
                            _hs = None
                        # untracked-ok: observational; failure silent.
                        self.coordinator.hass.async_create_task(  # noqa: untracked-ok
                            _db.log_memory_episode(
                                node_id=f"room:{_slug}",
                                episode_type="sensor_dropout",
                                adjudication="unadjudicated",
                                adjudicated_by="unavailable_entities_sensor",
                                attrs={
                                    "entities": list(eids),
                                    "count": cur,
                                    "house_state": _hs,
                                },
                                source_ref=(
                                    "sensor.py:UnavailableEntitiesSensor"
                                ),
                            ),
                        )
            except Exception:  # noqa: BLE001
                pass
        self.__dict__["_memory_dropout_prev_count"] = cur
        return cur

    def _iter_configured(self):
        """Yield (entity_id, role, category) for every configured entity."""
        # v3.2.4 FIX: options overlays data (reconfigured values live in options)
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        for key in self._SENSOR_LIST_KEYS:
            for eid in config.get(key) or []:
                if eid:
                    yield eid, key, "sensor"
        for key in self._SENSOR_SINGLE_KEYS:
            eid = config.get(key)
            if eid:
                yield eid, key, "sensor"
        for key in self._ACTUATOR_LIST_KEYS:
            for eid in config.get(key) or []:
                if eid:
                    yield eid, key, "actuator"
        for key in self._ACTUATOR_SINGLE_KEYS:
            eid = config.get(key)
            if eid:
                yield eid, key, "actuator"

    @staticmethod
    def _unavailable_reason(state) -> str | None:
        """Best-effort reason an entity is not usable, derived from its HA state."""
        if state is None:
            return "entity_missing"  # not registered / removed from HA
        if state.state == "unavailable":
            # `restored` placeholder = HA rehydrated the entity but the
            # integration/device has not reported since the last restart
            # (device offline or integration not loaded) — the AV-closet case.
            if state.attributes.get("restored"):
                return "offline_since_restart"
            return "device_unreachable"
        if state.state == "unknown":
            return "state_unknown"
        return None

    def _reconciler(self):
        """Return the room's ActuatorReconciler, or None (None-safe)."""
        return getattr(self.coordinator, "_actuator_reconciler", None)

    def _unavailable_details(self) -> list[dict[str, Any]]:
        """Structured detail for every unavailable configured entity.

        Reconcile-on-Return (v5.8.0, D2.11): a currently-quarantined
        (flapping) actuator is surfaced here with reason "flapping" plus its
        transition_count + since even though it may report an "available"
        state — so a chronically flaky device is grep-visible next to the
        offline ones.
        """
        details: dict[str, dict[str, Any]] = {}
        reconciler = self._reconciler()
        flapping_ids: set[str] = set()
        if reconciler is not None:
            try:
                flapping_ids = {
                    f["entity_id"] for f in reconciler.flapping_entities()
                }
            except Exception:  # noqa: BLE001 — diagnostics must degrade
                flapping_ids = set()
        for eid, role, category in self._iter_configured():
            state = self.coordinator.hass.states.get(eid)
            is_unavail = state is None or state.state in ("unavailable", "unknown")
            is_flapping = eid in flapping_ids
            if not is_unavail and not is_flapping:
                continue
            entry = details.get(eid)
            if entry is None:
                since = None
                if state is not None and state.last_changed is not None:
                    since = state.last_changed.isoformat()
                entry = {
                    "entity_id": eid,
                    "roles": [],
                    "category": category,
                    "state": state.state if state is not None else "missing",
                    "reason": self._unavailable_reason(state),
                    "since": since,
                }
                # D2.11: flapping actuators get reason "flapping" +
                # transition_count + since (overrides the availability-derived
                # reason — a flapping device is the more actionable signal).
                if is_flapping and reconciler is not None:
                    detail = None
                    try:
                        detail = reconciler.flapping_detail(eid)
                    except Exception:  # noqa: BLE001
                        detail = None
                    if detail is not None:
                        entry["reason"] = "flapping"
                        entry["transition_count"] = detail.get("transition_count")
                        entry["since"] = detail.get("since")
                details[eid] = entry
            if role not in entry["roles"]:
                entry["roles"].append(role)
        return list(details.values())

    def _get_unavailable_entities(self) -> list[str]:
        """Flat list of unavailable entity_ids (backward-compatible)."""
        return [d["entity_id"] for d in self._unavailable_details()]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Structured breakdown of unavailable configured entities."""
        details = self._unavailable_details()
        sensors = [d["entity_id"] for d in details if d["category"] == "sensor"]
        actuators = [d["entity_id"] for d in details if d["category"] == "actuator"]
        attrs = {
            # Backward-compatible flat list (now spans inputs + actuators).
            "unavailable_entities": [d["entity_id"] for d in details],
            "details": details,
            "unavailable_sensors": sensors,
            "unavailable_actuators": actuators,
            "sensor_count": len(sensors),
            "actuator_count": len(actuators),
        }
        # Reconcile-on-Return (v5.8.0, D2.4): reconcile diagnostics. None-safe —
        # a room with no lights/fans has no reconciler, so we degrade to zeros.
        reconciler = self._reconciler()
        if reconciler is not None:
            try:
                attrs.update(reconciler.diagnostics())
            except Exception:  # noqa: BLE001 — diagnostics must degrade
                pass
        else:
            attrs.update({
                "reconciles_today": 0,
                "recent_reconciles": [],
                "reconcile_debounced_count": 0,
                "reconcile_coalesced_count": 0,
                "flapping_entities": [],
            })
        return attrs


class LastAutomationTriggerSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for last automation trigger (what caused occupancy detection)."""

    _attr_icon = ICON_LAST_TRIGGER
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "last_automation_trigger", "Last Automation Trigger")

    @property
    def native_value(self) -> str:
        """Return last trigger source."""
        source = self.coordinator._last_trigger_source
        if not source:
            return "None"
        return source.capitalize()
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return trigger details."""
        if not self.coordinator._last_trigger_source:
            return {}
        
        attrs = {
            "entity_id": self.coordinator._last_trigger_entity,
            "trigger_source": self.coordinator._last_trigger_source,
        }
        
        if self.coordinator._last_trigger_time:
            attrs["timestamp"] = self.coordinator._last_trigger_time.isoformat()
            time_ago = (dt_util.now() - self.coordinator._last_trigger_time).total_seconds()
            if time_ago < 60:
                attrs["time_ago"] = f"{int(time_ago)} seconds ago"
            elif time_ago < 3600:
                attrs["time_ago"] = f"{int(time_ago / 60)} minutes ago"
            else:
                attrs["time_ago"] = f"{int(time_ago / 3600)} hours ago"
        
        return attrs


class LastAutomationActionSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for last automation action (what automation did)."""

    _attr_icon = ICON_LAST_ACTION
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "last_automation_action", "Last Automation Action")

    @property
    def native_value(self) -> str:
        """Return last action description."""
        action = self.coordinator._last_action_description
        if not action:
            return "None"
        return action
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return action details."""
        if not self.coordinator._last_action_description:
            return {}
        
        attrs = {
            "entity_id": self.coordinator._last_action_entity,
            "action_type": self.coordinator._last_action_type,
        }
        
        if self.coordinator._last_action_time:
            attrs["timestamp"] = self.coordinator._last_action_time.isoformat()
            time_ago = (dt_util.now() - self.coordinator._last_action_time).total_seconds()
            if time_ago < 60:
                attrs["time_ago"] = f"{int(time_ago)} seconds ago"
            elif time_ago < 3600:
                attrs["time_ago"] = f"{int(time_ago / 60)} minutes ago"
            else:
                attrs["time_ago"] = f"{int(time_ago / 3600)} hours ago"
        
        return attrs




class LastAutomationTimeSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for last automation time (v3.2.6).
    
    Shows when the room automation last took an action as a timestamp.
    Useful for debugging automation timing and activity.
    """

    _attr_icon = "mdi:clock-check-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "last_automation_time", "Last Automation Time")

    @property
    def native_value(self) -> datetime | None:
        """Return timestamp of last automation action."""
        return self.coordinator._last_action_time
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional context about the last automation."""
        attrs = {}
        
        if self.coordinator._last_action_time:
            time_ago = (dt_util.now() - self.coordinator._last_action_time).total_seconds()
            if time_ago < 60:
                attrs["time_ago"] = f"{int(time_ago)} seconds ago"
            elif time_ago < 3600:
                attrs["time_ago"] = f"{int(time_ago / 60)} minutes ago"
            else:
                attrs["time_ago"] = f"{int(time_ago / 3600)} hours ago"
            
            attrs["action"] = self.coordinator._last_action_description or "Unknown"
            attrs["trigger"] = self.coordinator._last_trigger_source or "Unknown"
        else:
            attrs["time_ago"] = "Never"
        
        return attrs

class DevicesSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for device enumeration."""

    _attr_icon = ICON_DEVICES
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "devices", "Devices")

    @property
    def native_value(self) -> int:
        """Return total device count.
        
        v3.2.8.2: Counts both legacy (auto_switches/manual_switches) and
        new (auto_devices/manual_devices) fields without double-counting.
        """
        # v3.2.4 FIX: Merge entry.options with entry.data
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        count = 0
        count += len(config.get("lights", []))
        count += len(config.get("fans", []))
        count += len(config.get("humidity_fans", []))
        count += len(config.get("covers", []))
        
        # v3.2.8.2: Combine legacy + new auto/manual fields (avoid double-counting)
        auto_devices = set(config.get("auto_devices", []))
        auto_devices.update(config.get("auto_switches", []))
        count += len(auto_devices)
        
        manual_devices = set(config.get("manual_devices", []))
        manual_devices.update(config.get("manual_switches", []))
        count += len(manual_devices)

        # v3.3.5.5: Count media player, power sensors, energy sensor
        if config.get("room_media_player"):
            count += 1
        count += len(config.get("power_sensors", []))
        if config.get("energy_sensor"):
            count += 1

        return count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device details.
        
        v3.2.8.2: Returns combined lists of legacy + new auto/manual fields.
        """
        # v3.2.4 FIX: Merge entry.options with entry.data
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        
        # v3.2.8.2: Combine legacy + new auto/manual fields
        auto_devices = list(set(config.get("auto_devices", []) + config.get("auto_switches", [])))
        manual_devices = list(set(config.get("manual_devices", []) + config.get("manual_switches", [])))
        
        return {
            "lights": config.get("lights", []),
            "fans": config.get("fans", []),
            "humidity_fans": config.get("humidity_fans", []),
            "covers": config.get("covers", []),
            "auto_devices": auto_devices,
            "manual_devices": manual_devices,
            # Also include legacy fields for backward compatibility
            "auto_switches": config.get("auto_switches", []),
            "manual_switches": config.get("manual_switches", []),
            # v3.3.5.5: Media and energy devices
            "room_media_player": config.get("room_media_player"),
            "power_sensors": config.get("power_sensors", []),
            "energy_sensor": config.get("energy_sensor"),
        }


class DeviceStatusSensor(UniversalRoomEntity, SensorEntity):
    """Sensor showing parent device names (not entity IDs)."""

    _attr_icon = "mdi:devices"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "device_status", "Device Status")

    @property
    def native_value(self) -> str:
        """Return comma-separated device names, bounded to HA's 255-char state limit.

        v5.35.3: rooms with many devices (Laundry: 10) produced a >255-char
        state -> homeassistant.core ERROR "longer than 255, falling back to
        unknown" every update (~2/min log flood). The full list is already in
        the `device_list` attribute; the state degrades to a count when the
        joined string would exceed the limit.
        """
        device_names = self._get_device_names()
        if not device_names:
            return "No devices"
        joined = ", ".join(device_names)
        if len(joined) > 255:
            return f"{len(device_names)} devices (see device_list)"
        return joined

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device count and list."""
        device_names = self._get_device_names()
        return {
            "device_count": len(device_names),
            "device_list": device_names,
        }

    def _get_device_names(self) -> list[str]:
        """Get parent device names from entities."""
        from homeassistant.helpers import device_registry as dr, entity_registry as er

        entity_reg = er.async_get(self.hass)
        device_reg = dr.async_get(self.hass)

        # v3.2.4 FIX: Merge entry.options with entry.data
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        all_entities = []

        # Collect all entities from list-type keys
        for key in ["lights", "fans", "humidity_fans", "covers", "auto_switches", "manual_switches",
                     "power_sensors"]:
            all_entities.extend(config.get(key, []))

        # Collect single-entity keys
        for key in ["room_media_player", "energy_sensor"]:
            entity_id = config.get(key)
            if entity_id:
                all_entities.append(entity_id)

        device_names = set()
        for entity_id in all_entities:
            if entity_entry := entity_reg.async_get(entity_id):
                if entity_entry.device_id:
                    if device := device_reg.async_get(entity_entry.device_id):
                        device_names.add(device.name_by_user or device.name)

        return sorted(list(device_names))


class DaysSinceOccupiedSensor(UniversalRoomEntity, SensorEntity):
    """Sensor for days since room was last occupied."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_icon = "mdi:calendar-remove"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "days_since_occupied", "Days Since Occupied")

    @property
    def native_value(self) -> int | None:
        """Return days since last occupied."""
        if self.coordinator._last_occupied_time:
            elapsed = (dt_util.now() - self.coordinator._last_occupied_time).total_seconds()
            return int(elapsed / 86400)  # Convert seconds to days
        return None


class DatabaseStatusSensor(UniversalRoomEntity, SensorEntity):
    """Sensor showing database collection status and record counts."""

    _attr_icon = "mdi:database"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "database_status", "Database Status")
        self._counts = {"occupancy_events": 0, "environmental_data": 0, "energy_snapshots": 0}

    @property
    def available(self) -> bool:
        """Sensor available if database exists."""
        return DOMAIN in self.hass.data and "database" in self.hass.data[DOMAIN]

    @property
    def native_value(self) -> str:
        """Return database status."""
        if not self.available:
            return "Database Not Available"
        
        total = sum(self._counts.values())
        if total == 0:
            return "Collecting Data..."
        return f"{total} Records"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed record counts."""
        if not self.available:
            return {}
        
        return {
            "occupancy_events": self._counts.get("occupancy_events", 0),
            "environmental_data": self._counts.get("environmental_data", 0),
            "energy_snapshots": self._counts.get("energy_snapshots", 0),
            "total_records": sum(self._counts.values()),
            "database_file": self.hass.data[DOMAIN]["database"].db_file if self.available else None,
        }

    async def async_update(self) -> None:
        """Update record counts."""
        if not self.available:
            return
        
        database = self.hass.data[DOMAIN].get("database")
        if database:
            try:
                self._counts = await database.get_table_counts(self.coordinator.entry.entry_id)
            except Exception as e:
                _LOGGER.error("Error updating database status: %s", e)


# =============================================================================
# v3.6.17: AUTOMATION HEALTH SENSOR
# =============================================================================


class AutomationHealthSensor(UniversalRoomEntity, SensorEntity):
    """Composite sensor surfacing room automation internal state.

    Primary state is a rollup: normal / debouncing / grace_hold /
    failsafe / stuck_sensor.  All detail is in attributes so a single
    entity per room replaces 8+ individual diagnostic entities.

    Entity:  sensor.ura_<room>_automation_health
    Device:  the room device
    """

    _attr_icon = "mdi:heart-pulse"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "automation_health", "Automation Health")

    # -- primary state --------------------------------------------------

    @property
    def native_value(self) -> str:
        """Return the most significant active condition."""
        c = self.coordinator

        # Failsafe is highest priority
        if c._failsafe_fired:
            return "failsafe"

        # Stuck sensors
        now = dt_util.now()
        stuck = [
            eid for eid, since in c._sensor_on_since.items()
            if (now - since).total_seconds() > c._stuck_sensor_hours * 3600
        ]
        if stuck:
            return "stuck_sensor"

        # Grace hold (all sensors unavailable)
        if c._all_sensors_unavailable_since is not None:
            elapsed = (now - c._all_sensors_unavailable_since).total_seconds()
            if elapsed < c._unavail_grace_seconds:
                return "grace_hold"

        # Debounce pending
        if (
            c._occupancy_first_detected is not None
            and not (c.data or {}).get("occupied", False)
        ):
            return "debouncing"

        return "normal"

    # -- icon follows state ---------------------------------------------

    @property
    def icon(self) -> str:
        val = self.native_value
        return {
            "normal": "mdi:heart-pulse",
            "debouncing": "mdi:timer-sand",
            "grace_hold": "mdi:shield-half-full",
            "failsafe": "mdi:alert-octagon",
            "stuck_sensor": "mdi:motion-sensor-off",
        }.get(val, "mdi:heart-pulse")

    # -- attributes -----------------------------------------------------

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.coordinator
        now = dt_util.now()
        attrs: dict[str, Any] = {}

        # --- Tier 1: Occupancy session & failsafe ---
        if c._became_occupied_time and (c.data or {}).get("occupied", False):
            session_s = (now - c._became_occupied_time).total_seconds()
            attrs["session_duration_minutes"] = round(session_s / 60, 1)
            attrs["failsafe_remaining_minutes"] = max(
                0, round((4 * 3600 - session_s) / 60, 1)
            )
        else:
            attrs["session_duration_minutes"] = 0
            attrs["failsafe_remaining_minutes"] = None
        attrs["failsafe_fired"] = c._failsafe_fired

        # --- Tier 1: Stuck sensors ---
        stuck = []
        for eid, since in c._sensor_on_since.items():
            on_hours = (now - since).total_seconds() / 3600
            if on_hours > c._stuck_sensor_hours:
                stuck.append({"entity_id": eid, "on_hours": round(on_hours, 1)})
        attrs["stuck_sensors"] = stuck
        attrs["stuck_sensor_count"] = len(stuck)

        # --- Tier 1: Debounce ---
        if c._occupancy_first_detected is not None:
            elapsed = (now - c._occupancy_first_detected).total_seconds()
            attrs["debounce_active"] = elapsed < c._occupancy_debounce_seconds
            attrs["debounce_elapsed_seconds"] = round(elapsed, 1)
        else:
            attrs["debounce_active"] = False
            attrs["debounce_elapsed_seconds"] = None

        # --- Tier 1: Sensor grace period ---
        if c._all_sensors_unavailable_since is not None:
            elapsed = (now - c._all_sensors_unavailable_since).total_seconds()
            attrs["grace_active"] = elapsed < c._unavail_grace_seconds
            attrs["grace_remaining_seconds"] = max(
                0, round(c._unavail_grace_seconds - elapsed, 1)
            )
        else:
            attrs["grace_active"] = False
            attrs["grace_remaining_seconds"] = None

        # --- Tier 2: Sleep bypass ---
        if hasattr(c, "automation") and c.automation:
            attrs["sleep_bypass_count"] = c.automation._sleep_motion_count
        else:
            attrs["sleep_bypass_count"] = 0

        # --- Tier 2: Service call health ---
        if hasattr(c, "automation") and c.automation:
            a = c.automation
            attrs["service_calls_today"] = a._service_calls_today
            attrs["service_failures_today"] = a._service_failures_today
            # v4.2.22: Cover straggler tracking. cover_failures_today counts
            # individual blinds that did not reach commanded state after all
            # retries — surfaces hub/RF reliability issues that hub-acceptance
            # service calls would otherwise hide.
            attrs["cover_attempts_today"] = getattr(a, "_cover_attempts_today", 0)
            attrs["cover_failures_today"] = getattr(a, "_cover_failures_today", 0)
            last_fail = getattr(a, "_last_cover_failure_time", None)
            attrs["last_cover_failure"] = (
                last_fail.isoformat() if last_fail else None
            )
            attrs["last_cover_failure_entities"] = list(
                getattr(a, "_last_cover_failure_entities", [])
            )
        else:
            attrs["service_calls_today"] = 0
            attrs["service_failures_today"] = 0
            attrs["cover_attempts_today"] = 0
            attrs["cover_failures_today"] = 0
            attrs["last_cover_failure"] = None
            attrs["last_cover_failure_entities"] = []

        # --- Tier 2: Exit verify ---
        attrs["last_exit_verify_result"] = c._last_exit_verify_result
        if c._last_exit_verify_time:
            attrs["last_exit_verify_time"] = c._last_exit_verify_time.isoformat()
        else:
            attrs["last_exit_verify_time"] = None

        return attrs


# =============================================================================
# Reconcile-on-Return (v5.8.0, D2.12): per-room RoomReconcileSensor
# =============================================================================


class RoomReconcileSensor(UniversalRoomEntity, SensorEntity):
    """Per-room reconcile diagnostic. Prior art: AutomationHealthSensor.

    Entity: sensor.<room>_room_reconcile
    State:  reconciles_today (int)
    Attrs:  last_reconcile, reconciles_today, coalesced_count,
            last_skip_reason, would_reconcile {entity_id: desired_state}.

    Does NOT duplicate flapping_entities — that lives on
    sensor.<room>_unavailable_entities (D2.11).
    """

    _attr_icon = "mdi:backup-restore"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "room_reconcile", "Room Reconcile")

    def _reconciler(self):
        return getattr(self.coordinator, "_actuator_reconciler", None)

    @property
    def native_value(self) -> int:
        reconciler = self._reconciler()
        if reconciler is None:
            return 0
        try:
            return reconciler.reconciles_today
        except Exception:  # noqa: BLE001
            return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        reconciler = self._reconciler()
        if reconciler is None:
            return {
                "last_reconcile": None,
                "reconciles_today": 0,
                "coalesced_count": 0,
                "last_skip_reason": None,
                "would_reconcile": {},
            }
        try:
            return reconciler.room_sensor_attrs()
        except Exception:  # noqa: BLE001
            return {}


# =============================================================================
# v4.7.16 D2: ROOM SIGNAL INVENTORY SENSOR
# =============================================================================


class RoomSignalInventorySensor(UniversalRoomEntity, SensorEntity):
    """v4.7.16 D2: per-room BLE coverage + signal inventory diagnostic.

    Surfaces the CONF_SCANNER_AREAS-derived BLE tier classification plus
    booleans for which other signal sources are configured for this room
    (mmWave, PIR, camera). Pure introspection — no signal dispatch, no DB
    writes, no actuation. State and attributes derive lazily at read time
    (Bug Class #46 doctrine).

    State is a human-readable rolled-up label
    (Bug Class #47 — canonical UI surface):
      - "dense"                 ble_tier=1 + at least one PIR or mmWave
      - "sparse_with_fallback"  ble_tier=2
      - "sparse_no_fallback"    ble_tier=0 + at least one PIR/mmWave/camera
      - "pir_only"              ble_tier=0 + only PIR
      - "camera_only"           ble_tier=0 + only camera
      - "none"                  ble_tier=0 + no other signals

    Numeric ble_tier (1/2/0) lives in attributes for machine readers.

    Entity:  sensor.ura_<room>_signal_inventory
    Device:  the room device (same as AutomationHealthSensor)
    """

    _attr_icon = "mdi:radar"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "signal_inventory", "Signal Inventory")

    # ------------------------------------------------------------------
    # Lookups (lazy, fail-safe — no migration helper)
    # ------------------------------------------------------------------

    def _room_name(self) -> str:
        try:
            return self.coordinator.entry.data.get("room_name", "")
        except Exception:  # pragma: no cover - defensive
            return ""

    def _config(self) -> dict:
        try:
            entry = self.coordinator.entry
            return {**entry.data, **entry.options}
        except Exception:  # pragma: no cover - defensive
            return {}

    def _person_coord(self):
        try:
            return self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        except Exception:  # pragma: no cover - defensive
            return None

    def _ble_tier(self) -> int:
        pc = self._person_coord()
        if pc is None or not hasattr(pc, "get_ble_tier"):
            return 0
        try:
            return int(pc.get_ble_tier(self._room_name()))
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.debug(
                "RoomSignalInventorySensor: get_ble_tier failed for %s: %s",
                self._room_name(), exc,
            )
            return 0

    def _has_camera(self) -> bool:
        """Return True iff a camera is registered for THIS room's area_id
        AND the room has NOT opted out via D4.

        Post-review C2-H1 (HIGH): the prior implementation walked the
        zone tracker's `_camera_entity_ids` set, which is zone-scoped
        (cameras for all rooms in the zone, not filtered by area_id).
        That allowed a sibling room with a camera to falsely report
        `has_camera=True` for a camera-less room sharing the same zone.

        Fix: query CameraIntegrationManager.get_cameras_for_area(room_area)
        directly — the camera_manager is the canonical area→camera map
        (`_cameras_by_area` dict at camera_census.py:603). This is the
        same source `_discover_zone_cameras` consults, so a room's
        `has_camera` answer is now consistent with whether
        `tracker.register_camera` would have fired for THIS room's area.
        """
        cfg = self._config()
        if cfg.get(
            CONF_DISABLE_CAMERA_PRESENCE, DEFAULT_DISABLE_CAMERA_PRESENCE
        ):
            return False
        room_area = cfg.get(CONF_AREA_ID)
        if not room_area:
            return False
        # Query camera_manager directly for cameras in THIS room's area.
        # camera_manager.get_cameras_for_area is keyed by area_id, so the
        # answer is room-scoped (not zone-scoped) by construction.
        try:
            camera_manager = self.hass.data.get(DOMAIN, {}).get(
                "camera_manager"
            )
        except Exception:  # pragma: no cover - defensive
            return False
        if camera_manager is None:
            return False
        try:
            cameras_in_area = camera_manager.get_cameras_for_area(room_area)
        except Exception:  # pragma: no cover - defensive
            return False
        return bool(cameras_in_area)

    # ------------------------------------------------------------------
    # State + attributes
    # ------------------------------------------------------------------

    @property
    def native_value(self) -> str:
        cfg = self._config()
        ble_tier = self._ble_tier()
        has_mmwave = bool(cfg.get(CONF_MMWAVE_SENSORS) or [])
        has_pir = bool(cfg.get(CONF_MOTION_SENSORS) or [])
        has_camera = self._has_camera()

        if ble_tier == 1:
            # Post-review A5 (MEDIUM): the prior ternary had identical arms
            # ("dense" if (has_mmwave or has_pir) else "dense") — dead branch.
            # Reviewer A's recommended resolution: Tier 1 = "dense" period.
            # A ble_tier=1 room without mmWave/PIR is still structurally
            # "dense BLE coverage" from the scanner perspective; the absence
            # of occupancy sensors is visible via has_mmwave/has_pir attrs.
            return "dense"
        if ble_tier == 2:
            return "sparse_with_fallback"
        # ble_tier == 0
        if has_pir and not has_camera:
            return "pir_only"
        if has_camera and not has_pir and not has_mmwave:
            return "camera_only"
        if has_pir or has_mmwave or has_camera:
            return "sparse_no_fallback"
        return "none"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cfg = self._config()
        ble_tier = self._ble_tier()
        return {
            # Numeric tier lives in attrs only — Bug Class #47.
            "ble_tier": ble_tier,
            "has_mmwave": bool(cfg.get(CONF_MMWAVE_SENSORS) or []),
            "has_pir": bool(cfg.get(CONF_MOTION_SENSORS) or []),
            "has_camera": self._has_camera(),
            "has_ble_fallback_room": ble_tier == 2,
            "scanner_areas": list(cfg.get(CONF_SCANNER_AREAS) or []),
            "area_id": cfg.get(CONF_AREA_ID),
            "disable_camera_presence": bool(
                cfg.get(
                    CONF_DISABLE_CAMERA_PRESENCE,
                    DEFAULT_DISABLE_CAMERA_PRESENCE,
                )
            ),
        }


# =============================================================================
# v3.12.0 M4: AI AUTOMATION STATUS SENSOR
# =============================================================================


class AIAutomationStatusSensor(UniversalRoomEntity, SensorEntity):
    """Tracks AI rule and automation chain execution.

    Reports whether AI rules or chained automations are configured,
    and exposes execution tracking attributes for diagnostics.

    Entity:  sensor.ura_<room>_ai_automation_status
    Device:  the room device
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:robot"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "ai_automation_status", "AI Automation Status")

    @property
    def native_value(self) -> str:
        """Return 'active' if any AI rules or chained automations are configured."""
        rules = self.coordinator._get_config(CONF_AI_RULES, [])
        chains = self.coordinator._get_config(CONF_AUTOMATION_CHAINS, {})
        if rules or chains:
            return "active"
        return "inactive"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return AI automation diagnostic attributes."""
        return {
            "chained_automations": self.coordinator._get_config(CONF_AUTOMATION_CHAINS, {}),
            "ai_rules_count": len(self.coordinator._get_config(CONF_AI_RULES, [])),
            "last_trigger": getattr(self.coordinator, '_last_trigger_event', None),
            "last_trigger_time": getattr(self.coordinator, '_last_trigger_time_str', None),
            "conflict_detected": getattr(self.coordinator, '_conflict_detected', False),
            "last_conflicts": getattr(self.coordinator, '_last_conflicts', [])[-5:],
        }


# =============================================================================
# v3.2.0: PERSON TRACKING SENSORS
# =============================================================================


class CurrentOccupantsSensor(UniversalRoomEntity, SensorEntity):
    """Sensor: List of current occupants in room.
    
    v3.2.8.3: Added person_coordinator subscription for real-time updates
    """
    
    _attr_icon = "mdi:account-multiple"
    
    def __init__(self, coordinator) -> None:
        """Initialize."""
        # v3.2.6: Renamed from "Current Occupants" to "Identified People"
        # v3.5.x: unique_id updated to "identified_people" to match entity name
        # Migration in __init__.py renames existing "current_occupants" entities
        super().__init__(coordinator, "identified_people", "Identified People")
        self._unsub_person_coordinator = None
    
    async def async_added_to_hass(self) -> None:
        """Subscribe to person_coordinator updates when added to hass.
        
        v3.2.8.3: Enables real-time updates when person tracking changes
        """
        await super().async_added_to_hass()
        
        # Subscribe to person_coordinator updates
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        if person_coordinator:
            self._unsub_person_coordinator = person_coordinator.async_add_listener(
                self._handle_person_update
            )
    
    async def async_will_remove_from_hass(self) -> None:
        """Clean up person_coordinator subscription."""
        if self._unsub_person_coordinator:
            self._unsub_person_coordinator()
            self._unsub_person_coordinator = None

    @callback
    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update.

        v3.2.8.3: Called when person tracking data changes
        """
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> str:
        """Return comma-separated list of occupants."""
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        if not person_coordinator:
            return "None"
        
        # Get room name from coordinator entry
        room_name = self.coordinator.entry.data.get("room_name", "")
        
        # Get persons in this room
        persons = person_coordinator.get_persons_in_room(room_name)
        
        if not persons:
            return "None"
        
        # Format names nicely (capitalize first letter)
        formatted_names = [p.replace('_', ' ').title() for p in persons]
        
        return ", ".join(formatted_names)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        if not person_coordinator:
            return {}
        
        room_name = self.coordinator.entry.data.get("room_name", "")
        persons = person_coordinator.get_persons_in_room(room_name)
        
        # Get confidence for each person
        person_details = {}
        for person_id in persons:
            confidence = person_coordinator.get_person_confidence(person_id)
            person_details[person_id] = {
                "confidence": round(confidence, 2),
                "confidence_level": (
                    "high" if confidence >= 0.8 else
                    "medium" if confidence >= 0.5 else
                    "low"
                )
            }
        
        return {
            "person_ids": persons,
            "person_details": person_details,
            "count": len(persons)
        }


class OccupantCountSensor(UniversalRoomEntity, SensorEntity):
    """Sensor: Count of occupants in room.
    
    v3.2.8.3: Added person_coordinator subscription for real-time updates
    """
    
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "people"
    
    def __init__(self, coordinator) -> None:
        """Initialize."""
        # v3.2.6: Renamed from "Occupant Count" to "Identified People Count"
        # v3.5.x: unique_id updated to "identified_people_count" to match entity name
        # Migration in __init__.py renames existing "occupant_count" entities
        super().__init__(coordinator, "identified_people_count", "Identified People Count")
        self._unsub_person_coordinator = None
    
    async def async_added_to_hass(self) -> None:
        """Subscribe to person_coordinator updates when added to hass.
        
        v3.2.8.3: Enables real-time updates when person tracking changes
        """
        await super().async_added_to_hass()
        
        # Subscribe to person_coordinator updates
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        if person_coordinator:
            self._unsub_person_coordinator = person_coordinator.async_add_listener(
                self._handle_person_update
            )
    
    async def async_will_remove_from_hass(self) -> None:
        """Clean up person_coordinator subscription."""
        if self._unsub_person_coordinator:
            self._unsub_person_coordinator()
            self._unsub_person_coordinator = None

    @callback
    def _handle_person_update(self) -> None:
        """Handle person_coordinator update - trigger state update.

        v3.2.8.3: Called when person tracking data changes
        """
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> int:
        """Return count of occupants."""
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        if not person_coordinator:
            return 0
        
        room_name = self.coordinator.entry.data.get("room_name", "")
        persons = person_coordinator.get_persons_in_room(room_name)
        
        return len(persons)


class LastOccupantSensor(UniversalRoomEntity, SensorEntity):
    """Sensor: Last person who occupied room."""
    
    _attr_icon = "mdi:account-clock"
    
    def __init__(self, coordinator) -> None:
        """Initialize."""
        # v3.2.6: Renamed from "Last Occupant" to "Last Identified Person"
        # v3.5.x: unique_id updated to "last_identified_person" to match entity name
        # Migration in __init__.py renames existing "last_occupant" entities
        super().__init__(coordinator, "last_identified_person", "Last Identified Person")
    
    @property
    def native_value(self) -> str:
        """Return last occupant."""
        database = self.hass.data[DOMAIN].get("database")
        
        if not database:
            return "Unknown"
        
        room_id = self.coordinator.entry.entry_id
        
        # Get occupants from database (async handled in update)
        if hasattr(self, '_last_occupant'):
            return self._last_occupant
        
        return "Unknown"
    
    async def async_update(self) -> None:
        """Update last occupant from database."""
        database = self.hass.data[DOMAIN].get("database")
        
        if not database:
            return
        
        room_name = self.coordinator.entry.data.get("room_name", "")
        
        try:
            # Get most recent visit
            cursor = await database._db.execute("""
                SELECT person_id, entry_time
                FROM person_visits
                WHERE room_id = ?
                ORDER BY entry_time DESC
                LIMIT 1
            """, (room_name,))
            
            row = await cursor.fetchone()
            
            if row:
                person_id = row['person_id']
                self._last_occupant = person_id.replace('_', ' ').title()
                self._last_occupant_time = row['entry_time']
            else:
                self._last_occupant = "Unknown"
                self._last_occupant_time = None
                
        except Exception as e:
            _LOGGER.error("Error getting last occupant: %s", e)
            self._last_occupant = "Unknown"
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        attrs = {}
        
        if hasattr(self, '_last_occupant_time') and self._last_occupant_time:
            # v4.2.9: Guard .isoformat() — DB returns strings, not datetime objects
            if isinstance(self._last_occupant_time, str):
                attrs["last_seen"] = self._last_occupant_time
            else:
                attrs["last_seen"] = self._last_occupant_time.isoformat()

            # Calculate time ago
            now = dt_util.utcnow()
            last_time = dt_util.parse_datetime(
                self._last_occupant_time if isinstance(self._last_occupant_time, str)
                else self._last_occupant_time.isoformat()
            )
            if last_time is None:
                last_time = now
            elif last_time.tzinfo is None:
                from datetime import timezone
                last_time = last_time.replace(tzinfo=timezone.utc)
            time_diff = now - last_time
            attrs["time_ago"] = str(time_diff).split('.')[0]
        
        return attrs


class LastOccupantTimeSensor(UniversalRoomEntity, SensorEntity):
    """Sensor: Timestamp of last occupant."""
    
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    
    def __init__(self, coordinator) -> None:
        """Initialize."""
        # v3.2.6: Renamed from "Last Occupant Time" to "Last Identified Time"
        # v3.5.x: unique_id updated to "last_identified_time" to match entity name
        # Migration in __init__.py renames existing "last_occupant_time" entities
        super().__init__(coordinator, "last_identified_time", "Last Identified Time")
    
    @property
    def native_value(self) -> datetime | None:
        """Return timestamp of last occupant."""
        database = self.hass.data[DOMAIN].get("database")
        
        if not database:
            return None
        
        if hasattr(self, '_last_time'):
            return self._last_time
        
        return None
    
    async def async_update(self) -> None:
        """Update last occupant time from database."""
        database = self.hass.data[DOMAIN].get("database")
        
        if not database:
            return
        
        room_name = self.coordinator.entry.data.get("room_name", "")
        
        try:
            cursor = await database._db.execute("""
                SELECT entry_time
                FROM person_visits
                WHERE room_id = ?
                ORDER BY entry_time DESC
                LIMIT 1
            """, (room_name,))
            
            row = await cursor.fetchone()
            
            if row:
                entry_time = row['entry_time']
                # v4.2.9: Use parse_datetime for robust tz-aware parsing
                if isinstance(entry_time, str):
                    self._last_time = dt_util.parse_datetime(entry_time)
                else:
                    self._last_time = entry_time
                if self._last_time is not None and self._last_time.tzinfo is None:
                    from datetime import timezone
                    self._last_time = self._last_time.replace(tzinfo=timezone.utc)
            else:
                self._last_time = None
                
        except Exception as e:
            _LOGGER.error("Error getting last occupant time: %s", e)
            self._last_time = None


class PersonTrackingStatusSensor(UniversalRoomEntity, SensorEntity):
    """
    v3.2.8.1: Room-level person tracking diagnostic sensor.
    
    Shows tracking quality and status for all persons in this room,
    helping debug why occupancy detection may not be working.
    """
    
    _attr_icon = "mdi:account-search"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    
    def __init__(self, coordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "person_tracking_status", "Person Tracking Status")
    
    @property
    def native_value(self) -> str:
        """Return summary of person tracking status in this room."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            
            if not person_coordinator or not person_coordinator.data:
                return "No tracking data"
            
            room_name = self.coordinator.entry.data.get("room_name", "")
            if not room_name:
                return "Room not configured"
            
            # Get persons in this room
            persons_in_room = []
            for person_name, person_info in person_coordinator.data.items():
                location = person_info.get("location", "")
                if location == room_name:
                    persons_in_room.append({
                        "person": person_name,
                        "status": person_info.get("tracking_status", "lost"),
                        "confidence": person_info.get("confidence", 0),
                        "method": person_info.get("method", "none"),
                    })
            
            if not persons_in_room:
                return "No persons in room"
            
            # Count by status
            active_count = sum(1 for p in persons_in_room if p["status"] == "active")
            stale_count = sum(1 for p in persons_in_room if p["status"] == "stale")
            lost_count = sum(1 for p in persons_in_room if p["status"] == "lost")
            
            # Return summary
            parts = []
            if active_count > 0:
                parts.append(f"{active_count} active")
            if stale_count > 0:
                parts.append(f"{stale_count} stale")
            if lost_count > 0:
                parts.append(f"{lost_count} lost")
            
            return ", ".join(parts)
            
        except Exception as e:
            _LOGGER.error("Error in PersonTrackingStatus.native_value for room '%s': %s", 
                         self.coordinator.entry.data.get("room_name", ""), e, exc_info=True)
            return "Error"
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed tracking information."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            
            if not person_coordinator or not person_coordinator.data:
                return {}
            
            room_name = self.coordinator.entry.data.get("room_name", "")
            if not room_name:
                return {}
            
            # Build detailed person tracking info
            persons_in_room = []
            for person_name, person_info in person_coordinator.data.items():
                location = person_info.get("location", "")
                if location == room_name:
                    persons_in_room.append({
                        "person": person_name,
                        "status": person_info.get("tracking_status", "lost"),
                        "confidence": round(person_info.get("confidence", 0), 2),
                        "method": person_info.get("method", "none"),
                        "bermuda_area": person_info.get("bermuda_area", "N/A"),
                    })
            
            return {
                "room_name": room_name,
                "persons_in_room": persons_in_room,
                "total_persons": len(persons_in_room),
            }
            
        except Exception as e:
            _LOGGER.error("Error in PersonTrackingStatus.extra_state_attributes: %s", e)
            return {}


# v3.3.0: Pattern learning and prediction sensors

class PersonLikelyNextRoomSensor(AggregationEntity, SensorEntity):
    """Predicted next room for a tracked person.

    v4.0.0-B2: Uses Bayesian predictor as primary source, falls back to
    pattern_learner (frequency-based) when Bayesian has no data.
    Preserves existing entity_id and unique_id — no breaking change.
    """

    _attr_icon = "mdi:map-marker-path"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, person_id: str) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._person_id = person_id
        self._attr_unique_id = f"{DOMAIN}_person_{person_id.lower()}_likely_next_room"
        self._attr_name = f"{person_id} Likely Next Room"
        self._cached_prediction: dict | None = None
        self._last_camera_sighting: dict | None = None
        self._prediction_source: str = "none"

    async def async_update(self) -> None:
        """Fetch prediction — Bayesian primary, frequency fallback."""
        self._cached_prediction = None
        self._prediction_source = "none"

        # v4.0.0-B2: Try Bayesian predictor first
        try:
            bayesian = self.hass.data.get(DOMAIN, {}).get("bayesian_predictor")
            if bayesian is not None:
                pred = bayesian.predict_room_at_time(
                    self._person_id, dt_util.now()
                )
                if pred is not None and pred.get("learning_status") != "insufficient_data":
                    self._cached_prediction = {
                        "next_room": pred.get("top_room"),
                        "confidence": pred.get("probability"),
                        "sample_size": None,
                        "reliability": pred.get("learning_status"),
                        "alternatives": [
                            a.get("room") for a in (pred.get("alternatives") or [])
                        ],
                        "predicted_path": None,
                        "current_room": "",
                    }
                    self._prediction_source = "bayesian"
        except Exception as e:
            _LOGGER.debug(
                "Bayesian prediction failed for %s, falling back: %s",
                self._person_id, e,
            )

        # v4.6.2 D3: B6 away_typical — when Bayesian has no usable cell data,
        # check geofence + cell-staleness before falling to frequency learner.
        # "away_typical" is returned instead of "unknown" when the person is
        # geofence-away AND the cell is empty or stale — school/work-day cells,
        # seasonal transitions, etc. Returns early so native_value reflects it.
        if self._cached_prediction is None:
            try:
                from .bayesian_predictor import (
                    is_cell_stale as _is_cell_stale,
                    _hour_to_time_bin as _h2tb,
                    _day_type as _dt,
                )
                person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
                database = self.hass.data.get(DOMAIN, {}).get("database")
                geofence_away = False
                if person_coordinator is not None:
                    loc = person_coordinator.data.get(self._person_id, {}).get("location")
                    geofence_away = loc == "away"
                if geofence_away and database is not None:
                    now_local = dt_util.now()
                    time_bin = _h2tb(now_local.hour)
                    day_type = _dt(now_local)
                    # v4.6.2 review fix B#3: read the live Number entity
                    # state, NOT entry.options. The Number is a RestoreEntity
                    # (URA Mirror Pattern) — user changes update the entity
                    # state and persist across restarts via RestoreEntity, but
                    # they DO NOT write back to entry.options. Reading options
                    # gives the install-time seed forever, making the slider
                    # dead config.
                    staleness_days = 14
                    try:
                        _staleness_state = self.hass.states.get(
                            f"number.ura_coordinator_manager_bayesian_cell_staleness_days"
                        )
                        if _staleness_state is not None and _staleness_state.state not in (
                            "unknown", "unavailable", None,
                        ):
                            staleness_days = int(float(_staleness_state.state))
                    except Exception:
                        pass
                    stale = await _is_cell_stale(
                        database, self._person_id, time_bin, day_type, staleness_days
                    )
                    if stale:
                        _LOGGER.debug(
                            "D3: %s is geofence-away and cell (%d,%d) is stale (%dd) — away_typical",
                            self._person_id, time_bin, day_type, staleness_days,
                        )
                        self._cached_prediction = {
                            "next_room": "away_typical",
                            "confidence": None,
                            "sample_size": None,
                            "reliability": "away_typical",
                            "alternatives": [],
                            "predicted_path": None,
                            "current_room": "",
                        }
                        self._prediction_source = "away_typical"
            except Exception as e:
                _LOGGER.debug("D3 away_typical check failed for %s: %s", self._person_id, e)

        # Fallback to frequency-based pattern_learner
        if self._cached_prediction is None:
            try:
                pattern_learner = self.hass.data.get(DOMAIN, {}).get("pattern_learner")
                person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")

                if pattern_learner and person_coordinator:
                    person_data = person_coordinator.data.get(self._person_id, {})
                    current_room = person_data.get("location")

                    if current_room and current_room not in ("unknown", "away", "home"):
                        self._cached_prediction = await pattern_learner.predict_next_room(
                            self._person_id, current_room
                        )
                        if self._cached_prediction:
                            self._prediction_source = "frequency"
            except Exception as e:
                _LOGGER.error(
                    "Error updating PersonLikelyNextRoomSensor for %s: %s",
                    self._person_id, e,
                )

        # v4.6.0: Write successful prediction to shared cache so
        # TransitionDetector._score_prediction() can read it at transition time.
        # Only written when a prediction exists; stale entries are fine
        # (scorer applies its own 30-min staleness gate).
        if self._cached_prediction is not None:
            try:
                raw_alts = self._cached_prediction.get("alternatives") or []
                # Bayesian path returns [str, ...]; frequency path returns
                # [{"room": str, "confidence": float}, ...].  Normalise to [str, ...].
                alt_rooms: list[str] = []
                for a in raw_alts:
                    if isinstance(a, str):
                        alt_rooms.append(a)
                    elif isinstance(a, dict):
                        room = a.get("room")
                        if room:
                            alt_rooms.append(room)
                if DOMAIN not in self.hass.data:
                    return
                self.hass.data[DOMAIN].setdefault(
                    "next_room_predictions", {}
                )[self._person_id] = {
                    "top": self._cached_prediction.get("next_room"),
                    "alternatives": alt_rooms[:2],
                    "confidence": self._cached_prediction.get("confidence") or 0.0,
                    "source": self._prediction_source,
                    "timestamp": dt_util.utcnow().isoformat(),
                }
            except Exception as e:
                _LOGGER.debug(
                    "Next-room prediction cache write failed for %s: %s",
                    self._person_id, e,
                )

        # v3.5.2: Fetch camera sighting for transit validation attribute
        try:
            transit_validator = self.hass.data.get(DOMAIN, {}).get("transit_validator")
            if transit_validator and self._cached_prediction:
                self._last_camera_sighting = transit_validator.get_last_camera_sighting(
                    self._person_id
                )
            else:
                self._last_camera_sighting = None
        except Exception:
            self._last_camera_sighting = None

    @property
    def native_value(self) -> str | None:
        """Return predicted next room from cache."""
        if self._cached_prediction:
            return self._cached_prediction.get("next_room")
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return prediction details from cache."""
        attrs: dict[str, Any] = {
            "source": self._prediction_source,
        }
        if not self._cached_prediction:
            return attrs
        sighting = self._last_camera_sighting
        ts = sighting.get("timestamp") if sighting else None
        if ts and hasattr(ts, "isoformat"):
            ts = ts.isoformat()
        attrs.update({
            "confidence": self._cached_prediction.get("confidence"),
            "sample_size": self._cached_prediction.get("sample_size"),
            "reliability": self._cached_prediction.get("reliability"),
            "alternatives": self._cached_prediction.get("alternatives"),
            "predicted_path": self._cached_prediction.get("predicted_path"),
            "current_room": self._cached_prediction.get("current_room", ""),
            # v3.5.2: Camera validation attributes
            "camera_last_seen": ts,
            "camera_last_room": sighting.get("room") if sighting else None,
            "transit_camera_validated": sighting is not None,
        })
        return attrs


class PersonCurrentPathSensor(AggregationEntity, SensorEntity):
    """Current movement path (last 3-4 rooms visited)."""
    
    _attr_icon = "mdi:routes"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, person_id: str) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._person_id = person_id
        self._attr_unique_id = f"{DOMAIN}_person_{person_id.lower()}_current_path"
        self._attr_name = f"{person_id} Current Path"
    
    @property
    def native_value(self) -> Optional[str]:
        """Return current path as string."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            if not person_coordinator:
                return None
            
            # Get person data
            person_data = person_coordinator.data.get(self._person_id, {})
            
            # Build path from recent_path + current location
            recent_path = person_data.get("recent_path", [])
            current_location = person_data.get("location", "")
            
            # Combine into path
            if recent_path and current_location:
                path = recent_path[-3:] + [current_location]  # Last 3 + current
            elif current_location:
                path = [current_location]
            else:
                path = recent_path[-4:] if recent_path else []
            
            if not path:
                return None
            
            return " → ".join(path)
            
        except Exception as e:
            _LOGGER.error(f"Error in PersonCurrentPathSensor: {e}")
            return None
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return path details."""
        try:
            person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
            if not person_coordinator:
                return {}
            
            person_data = person_coordinator.data.get(self._person_id, {})
            current_location = person_data.get("location", "")
            recent_path = person_data.get("recent_path", [])
            
            return {
                "current_location": current_location,
                "recent_path": recent_path,
                "path_length": len(recent_path) + (1 if current_location else 0)
            }
            
        except Exception as e:
            _LOGGER.error(f"Error in PersonCurrentPathSensor attributes: {e}")
            return {}


# ============================================================================
# v3.5.0: CENSUS SENSORS
# Integration-level sensors backed by PersonCensus (camera_census.py)
# ============================================================================


class _CensusBaseSensor(AggregationEntity, SensorEntity):
    """Base class for census sensors.

    Reads data from hass.data[DOMAIN]["census"] (PersonCensus instance).
    Gracefully returns 0 / unavailable if census has not run yet or
    camera integration is not configured.

    Subscribes to SIGNAL_CENSUS_UPDATED for immediate push updates
    when event-driven census triggers (v3.10.1).
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize census base sensor."""
        super().__init__(hass, entry)

    async def async_added_to_hass(self) -> None:
        """Subscribe to census updates for immediate push."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_CENSUS_UPDATED

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CENSUS_UPDATED,
                self._handle_census_update,
            )
        )

    @callback
    def _handle_census_update(self, data: dict) -> None:
        """Handle census update signal — push state immediately."""
        self.async_schedule_update_ha_state()

    def _get_census(self):
        """Return last FullCensusResult or None."""
        census = self.hass.data.get(DOMAIN, {}).get("census")
        if census is None:
            return None
        return census.last_result


class URAPersonsInHouseSensor(_CensusBaseSensor):
    """Total persons counted inside the house (camera + BLE)."""

    _attr_icon = "mdi:home-account"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_persons_in_house"
        self._attr_name = "Persons In House"

    @property
    def native_value(self) -> int:
        """Return total persons inside the house."""
        result = self._get_census()
        if result is None:
            return 0
        return result.house.total_persons

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional census attributes."""
        result = self._get_census()
        if result is None:
            return {}
        attrs = {
            "identified_count": result.house.identified_count,
            "unidentified_count": result.house.unidentified_count,
            "confidence": result.house.confidence,
            "source_agreement": result.house.source_agreement,
            "frigate_count": result.house.frigate_count,
            "unifi_count": result.house.unifi_count,
            "degraded_mode": result.house.degraded_mode,
            "active_platforms": result.house.active_platforms,
            "last_updated": result.timestamp.isoformat() if result.timestamp else None,
        }
        # v3.10.1 enhanced census attributes
        if result.house.enhanced_census:
            attrs["wifi_guest_floor"] = result.house.wifi_guest_floor
            attrs["camera_unrecognized"] = result.house.camera_unrecognized
            attrs["peak_held"] = result.house.peak_held
            attrs["peak_age_minutes"] = result.house.peak_age_minutes
            attrs["face_recognized_persons"] = result.house.face_recognized_persons
            attrs["enhanced_census"] = True
            # Cycle census_ble_cancel_unrecognized (2026-07-13): per-cycle
            # count of unrecognized camera contributions cancelled by BLE
            # area correlation. Zero when no residents were BLE-here-in-area
            # (or when person_coordinator is unavailable — I3 graceful).
            attrs["ble_cancelled_count"] = result.house.ble_cancelled_count
        # v5.9.0 D-E observability: same-area dedup contributions + pending
        # sustain-latch + naive-sum diagnostic. Read directly from the
        # PersonCensus instance so the shape lines up with build-time state.
        try:
            census = self.hass.data.get(DOMAIN, {}).get("census")
            if census is not None:
                attrs["area_contributions"] = dict(
                    getattr(census, "_last_area_contributions", {}) or {}
                )
                attrs["raw_pre_dedup_sum"] = int(
                    getattr(census, "_last_raw_pre_dedup_sum", 0) or 0
                )
                from homeassistant.util import dt as _dt_util
                pending_info = census.get_pending_peak_info("house", _dt_util.now())
                attrs["pending_peak"] = pending_info
                # Stuck-Signal Watchdog D1 (v5.35.0): per-camera stuck
                # entries discovered this tick. Empty on healthy.
                # B L-3 fix-up 2026-07-28: use public accessor.
                if hasattr(census, "get_stuck_cameras"):
                    attrs["stuck_cameras"] = census.get_stuck_cameras()
                else:
                    attrs["stuck_cameras"] = list(
                        getattr(census, "_last_stuck_cameras", []) or []
                    )
        except Exception:  # pragma: no cover - defensive
            _LOGGER.debug("Failed to attach v5.9.0 census observability attrs", exc_info=True)
        return attrs


class URAIdentifiedPersonsInHouseSensor(_CensusBaseSensor):
    """Number of identified (named) persons inside the house."""

    _attr_icon = "mdi:account-check"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_identified_persons_in_house"
        self._attr_name = "Identified Persons In House"

    @property
    def native_value(self) -> int:
        """Return count of identified persons."""
        result = self._get_census()
        if result is None:
            return 0
        return result.house.identified_count

    @property
    def extra_state_attributes(self) -> dict:
        """Return identified person list and source details."""
        result = self._get_census()
        if result is None:
            return {}
        import json
        return {
            "person_list": json.dumps(result.house.identified_persons),
            "ble_confirmed": result.ble_persons,
            "face_confirmed": result.face_persons,
            "confidence": result.house.confidence,
        }


class URAUnidentifiedPersonsInHouseSensor(_CensusBaseSensor):
    """Number of unidentified (guest) persons inside the house."""

    _attr_icon = "mdi:account-question"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_unidentified_persons_in_house"
        self._attr_name = "Unidentified Persons In House"

    @property
    def native_value(self) -> int:
        """Return count of unidentified (guest) persons."""
        result = self._get_census()
        if result is None:
            return 0
        return result.house.unidentified_count


class URAPersonsOnPropertySensor(_CensusBaseSensor):
    """Number of persons on the exterior property (egress + perimeter cameras)."""

    _attr_icon = "mdi:home-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_persons_on_property_exterior"
        self._attr_name = "Persons On Property (Exterior)"

    @property
    def native_value(self) -> int:
        """Return number of persons detected on property exterior."""
        result = self._get_census()
        if result is None:
            return 0
        return result.persons_outside

    @property
    def extra_state_attributes(self) -> dict:
        """Return exterior census attributes."""
        result = self._get_census()
        if result is None:
            return {}
        attrs = {
            "confidence": result.property_exterior.confidence,
            "source_agreement": result.property_exterior.source_agreement,
            "last_updated": result.timestamp.isoformat() if result.timestamp else None,
        }
        # v3.10.1 enhanced census attributes
        if result.property_exterior.enhanced_census:
            attrs["peak_held"] = result.property_exterior.peak_held
            attrs["peak_age_minutes"] = result.property_exterior.peak_age_minutes
        return attrs


class URATotalPersonsOnPropertySensor(_CensusBaseSensor):
    """Total persons on the whole property (house + exterior)."""

    _attr_icon = "mdi:account-group"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_total_persons_on_property"
        self._attr_name = "Total Persons On Property"

    @property
    def native_value(self) -> int:
        """Return total persons on property (house + exterior)."""
        result = self._get_census()
        if result is None:
            return 0
        return result.total_on_property

    @property
    def extra_state_attributes(self) -> dict:
        """Return combined census summary."""
        result = self._get_census()
        if result is None:
            return {}
        return {
            "inside_count": result.house.total_persons,
            "outside_count": result.persons_outside,
            "identified_total": result.house.identified_count,
            "unidentified_total": result.house.unidentified_count + result.property_exterior.unidentified_count,
            "house_confidence": result.house.confidence,
            "exterior_confidence": result.property_exterior.confidence,
            "last_updated": result.timestamp.isoformat() if result.timestamp else None,
        }


class URACensusConfidenceSensor(_CensusBaseSensor):
    """Census confidence level diagnostic sensor (disabled by default)."""

    _attr_icon = "mdi:gauge"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_confidence"
        self._attr_name = "Census Confidence"
        self._attr_state_class = None  # Enum state, not numeric

    @property
    def native_value(self) -> str:
        """Return overall census confidence level."""
        result = self._get_census()
        if result is None:
            return "none"
        return result.house.confidence

    @property
    def extra_state_attributes(self) -> dict:
        """Return confidence details."""
        result = self._get_census()
        if result is None:
            return {}
        return {
            "house_confidence": result.house.confidence,
            "house_source_agreement": result.house.source_agreement,
            "exterior_confidence": result.property_exterior.confidence,
        }


class URACensusValidationAgeSensor(_CensusBaseSensor):
    """Age of last census result in seconds (disabled by default)."""

    _attr_icon = "mdi:clock-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = "s"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_validation_age"
        self._attr_name = "Census Validation Age"

    @property
    def native_value(self) -> int | None:
        """Return seconds since last census run."""
        result = self._get_census()
        if result is None or result.timestamp is None:
            return None
        now = dt_util.utcnow()
        ts = result.timestamp
        # Ensure both are timezone-aware for subtraction
        if ts.tzinfo is None:
            from datetime import timezone  # v4.2.9: replaced pytz
            ts = ts.replace(tzinfo=timezone.utc)
        delta = now - ts
        return int(delta.total_seconds())


# ============================================================================
# v3.5.1: Perimeter Alert Status Sensor
# ============================================================================


class PerimeterAlertStatusSensor(AggregationEntity, SensorEntity):
    """Diagnostic sensor showing the last perimeter alert timestamp.

    Reads from the PerimeterAlertManager stored in hass.data[DOMAIN].
    Disabled by default.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_perimeter_alert_last_time"
        self._attr_name = "Last Perimeter Alert"

    @property
    def available(self) -> bool:
        """Available when the perimeter alert manager is active."""
        manager = self.hass.data.get(DOMAIN, {}).get("perimeter_alert_manager")
        return manager is not None and manager.is_active

    @property
    def native_value(self) -> str | None:
        """Return ISO timestamp of the last perimeter alert, or None."""
        manager = self.hass.data.get(DOMAIN, {}).get("perimeter_alert_manager")
        if not manager:
            return None
        last_time = manager.last_alert_time
        if last_time is None:
            return None
        return last_time.isoformat()

    @property
    def extra_state_attributes(self) -> dict:
        """Return diagnostic details about the alert manager."""
        manager = self.hass.data.get(DOMAIN, {}).get("perimeter_alert_manager")
        if not manager:
            return {"status": "not_initialized"}
        last_time = manager.last_alert_time
        return {
            "status": "active" if manager.is_active else "inactive",
            "last_alert_time": last_time.isoformat() if last_time else None,
        }


# ============================================================================
# build/exterior-track: ExteriorTrackLinker census counters (open-track derived)
# ============================================================================


class _ExteriorTrackCensusBase(AggregationEntity, SensorEntity):
    """Base for exterior-track census counters — reads from the linker.

    Device placement (operator-ratified 2026-08-06): the Security
    Coordinator device — exterior tracking is security-domain. Overrides
    AggregationEntity's whole-house default.
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_device_info = _security_device_info()
    # C-MED-1: dimensionless counter — no unit string. HA will not offer
    # unit conversion on a bare integer count.
    _counter_key: str = ""

    @property
    def available(self) -> bool:
        linker = self.hass.data.get(DOMAIN, {}).get("exterior_track_linker")
        return linker is not None and getattr(linker, "is_active", False)

    @property
    def native_value(self) -> int:
        linker = self.hass.data.get(DOMAIN, {}).get("exterior_track_linker")
        if linker is None:
            return 0
        try:
            return int(linker.census_counts().get(self._counter_key, 0))
        except Exception:  # noqa: BLE001
            return 0


class ExteriorPersonTracksActiveSensor(_ExteriorTrackCensusBase):
    """Number of OPEN exterior person tracks (one walker = 1, for the whole track)."""

    _attr_icon = "mdi:walk"
    _counter_key = "exterior_person_tracks_active"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_exterior_person_tracks_active"
        self._attr_name = "Outside: People Being Tracked"


class ExteriorVehicleTracksActiveSensor(_ExteriorTrackCensusBase):
    """Number of OPEN exterior vehicle tracks."""

    _attr_icon = "mdi:car"
    _counter_key = "exterior_vehicle_tracks_active"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_exterior_vehicle_tracks_active"
        self._attr_name = "Outside: Vehicles Being Tracked"


class ExteriorAnimalTracksActiveSensor(_ExteriorTrackCensusBase):
    """Number of OPEN exterior animal tracks (dog/cat/wildlife family)."""

    _attr_icon = "mdi:paw"
    _counter_key = "exterior_animal_tracks_active"
    _attr_entity_registry_enabled_default = False  # digest-only default cycle 1

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_exterior_animal_tracks_active"
        self._attr_name = "Outside: Animals Being Tracked"


class ExteriorUnidentifiedPersonsSensor(_ExteriorTrackCensusBase):
    """OPEN person tracks without a Frigate sub_label promotion."""

    _attr_icon = "mdi:account-question"
    # C-MED-1: dimensionless counter — drop the "persons" unit.
    _counter_key = "exterior_unidentified_persons"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_exterior_unidentified_persons"
        self._attr_name = "Outside: Unidentified People"


class ExteriorOpenTracksDiagnosticSensor(AggregationEntity, SensorEntity):
    # NOTE: device placement override to Security Coordinator applied in
    # __init__ below (operator-ratified 2026-08-06).
    """Diagnostic — full snapshot of OPEN exterior tracks (JSON in attrs).

    State = total open-track count across all labels; attributes carry the
    per-track path strings + classifications for dashboard consumption.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:map-marker-path"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_exterior_open_tracks"
        self._attr_name = "Outside: Open Tracks (diagnostic)"
        self._attr_device_info = _security_device_info()

    @property
    def available(self) -> bool:
        linker = self.hass.data.get(DOMAIN, {}).get("exterior_track_linker")
        return linker is not None and getattr(linker, "is_active", False)

    @property
    def native_value(self) -> int:
        linker = self.hass.data.get(DOMAIN, {}).get("exterior_track_linker")
        if linker is None:
            return 0
        try:
            counts = linker.census_counts()
            return int(
                counts.get("exterior_person_tracks_active", 0)
                + counts.get("exterior_vehicle_tracks_active", 0)
                + counts.get("exterior_animal_tracks_active", 0)
            )
        except Exception:  # noqa: BLE001
            return 0

    @property
    def extra_state_attributes(self) -> dict:
        linker = self.hass.data.get(DOMAIN, {}).get("exterior_track_linker")
        if linker is None:
            return {"status": "not_initialized"}
        try:
            attrs = {
                "open_tracks": linker.open_tracks_snapshot(),
                "counts": linker.census_counts(),
            }
            # BOOTSANITY-1 (2026-08-08): expose the allowlist install
            # state so the perimeter-camera install can be verified LIVE
            # from the dashboard (the boot-sanity WARNING alone is not
            # sufficient — on cold boot the end-of-setup guard cannot
            # fire, and a silent no-op install would otherwise be
            # invisible until an interior camera leaks into the census).
            try:
                attrs["allowlist_installed"] = bool(
                    getattr(linker, "_allowlist_installed", False)
                )
                attrs["allowlist_camera_count"] = len(
                    getattr(linker, "_allowed_cameras", ()) or ()
                )
            except Exception:  # noqa: BLE001
                pass
            # B-M3: per-camera unlinked-events counter (events that opened a
            # fresh single-hop track rather than extending an existing one —
            # diagnostic proxy for adjacency gaps).
            try:
                attrs["unlinked_events_by_camera"] = (
                    linker.unlinked_events_snapshot()
                )
            except Exception:  # noqa: BLE001
                pass
            # Hotfix 2026-08-06: dropped off-allowlist (interior) events —
            # visible so a leak like the playroom incident is diagnosable.
            try:
                attrs["ignored_offlist_events"] = dict(
                    getattr(linker, "_ignored_offlist_events", {})
                )
            except Exception:  # noqa: BLE001
                pass
            # Cycle 2 seam-split telemetry rider: per-(A,B) missed-intermediate
            # candidate counts (observability only; edges never change
            # automatically). Empty dict when nothing to report.
            # Fix-up (2026-08-06, B-LOW-2): counters are SINCE-BOOT — not
            # persisted across restart; cap at 64 keys with drop-oldest.
            # Frigate `_frigate_last_event_id` cache is PERSON-ONLY
            # (B-LOW-3): vehicle/animal snapshot events do not enter this
            # cache; vehicle NM uses the entity_picture live-fallback path.
            try:
                attrs["seam_split_candidates"] = (
                    linker.seam_split_snapshot()
                )
            except Exception:  # noqa: BLE001
                pass
            # Cycle-3 resolver-legs (2026-08-07): per-camera engine
            # table + sole-firing ratio (detector-reliability accused-
            # witness signal, observability only).
            try:
                mgr = self.hass.data.get(DOMAIN, {}).get(
                    "perimeter_alert_manager"
                )
                if mgr is not None and hasattr(mgr, "leg_firing_stats"):
                    attrs["leg_firing_by_camera"] = mgr.leg_firing_stats()
            except Exception:  # noqa: BLE001
                pass
            return attrs
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc)}


# ============================================================================
# v3.5.2: WAREHOUSED SENSORS — Entry/Exit Counts, Timestamps, Unidentified
# ============================================================================


class PersonsEnteredTodaySensor(AggregationEntity, SensorEntity):
    """Count of confirmed entry events via egress cameras since midnight.

    Resets at midnight. Restores today's count from the database on startup.
    """

    _attr_icon = "mdi:account-arrow-right"
    _attr_native_unit_of_measurement = "persons"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_persons_entered_today"
        self._attr_name = "Persons Entered Today"
        self._count: int = 0
        self._entries: list[dict] = []
        self._last_reset = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self._restoring: bool = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to egress events and restore today's count from DB."""
        await super().async_added_to_hass()
        self._restoring = True

        # Restore from database
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database:
            today_start = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
            events = await database.get_entry_exit_events_since(today_start, direction="entry")
            self._count = len(events)
            self._entries = events[-20:]

        # Subscribe to live egress events
        from homeassistant.core import callback as ha_callback
        from homeassistant.helpers.event import async_track_time_change

        self.hass.bus.async_listen("ura_person_egress_event", self._handle_egress_event)
        async_track_time_change(self.hass, self._midnight_reset, hour=0, minute=0, second=0)

        self._restoring = False
        self.async_write_ha_state()

    @callback
    def _handle_egress_event(self, event) -> None:
        """Handle an egress event from the bus."""
        if self._restoring:
            return
        if event.data.get("direction") != "entry":
            return
        self._count += 1
        self._entries.append({
            "person_id": event.data.get("person_id") or "unidentified",
            "time": event.data.get("timestamp"),
            "egress_camera": event.data.get("egress_camera"),
        })
        self.async_schedule_update_ha_state()

    @callback
    def _midnight_reset(self, now) -> None:
        """Reset count at midnight."""
        self._count = 0
        self._entries = []
        self._last_reset = now
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> int:
        """Return today's entry count."""
        return self._count

    @property
    def extra_state_attributes(self) -> dict:
        """Return entry details."""
        return {
            "entries": self._entries[-20:],
            "last_reset": self._last_reset.isoformat() if self._last_reset else None,
        }


class PersonsExitedTodaySensor(AggregationEntity, SensorEntity):
    """Count of confirmed exit events via egress cameras since midnight.

    Resets at midnight. Restores today's count from the database on startup.
    """

    _attr_icon = "mdi:account-arrow-left"
    _attr_native_unit_of_measurement = "persons"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_persons_exited_today"
        self._attr_name = "Persons Exited Today"
        self._count: int = 0
        self._entries: list[dict] = []
        self._last_reset = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self._restoring: bool = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to egress events and restore today's count from DB."""
        await super().async_added_to_hass()
        self._restoring = True

        # Restore from database
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database:
            today_start = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
            events = await database.get_entry_exit_events_since(today_start, direction="exit")
            self._count = len(events)
            self._entries = events[-20:]

        from homeassistant.helpers.event import async_track_time_change

        self.hass.bus.async_listen("ura_person_egress_event", self._handle_egress_event)
        async_track_time_change(self.hass, self._midnight_reset, hour=0, minute=0, second=0)

        self._restoring = False
        self.async_write_ha_state()

    @callback
    def _handle_egress_event(self, event) -> None:
        """Handle an egress event from the bus."""
        if self._restoring:
            return
        if event.data.get("direction") != "exit":
            return
        self._count += 1
        self._entries.append({
            "person_id": event.data.get("person_id") or "unidentified",
            "time": event.data.get("timestamp"),
            "egress_camera": event.data.get("egress_camera"),
        })
        self.async_schedule_update_ha_state()

    @callback
    def _midnight_reset(self, now) -> None:
        """Reset count at midnight."""
        self._count = 0
        self._entries = []
        self._last_reset = now
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> int:
        """Return today's exit count."""
        return self._count

    @property
    def extra_state_attributes(self) -> dict:
        """Return exit details."""
        return {
            "entries": self._entries[-20:],
            "last_reset": self._last_reset.isoformat() if self._last_reset else None,
        }


class LastPersonEntrySensor(AggregationEntity, SensorEntity):
    """Timestamp of the most recent confirmed entry event."""

    _attr_icon = "mdi:account-arrow-right"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_last_person_entry"
        self._attr_name = "Last Person Entry"
        self._last_entry: datetime | None = None
        self._last_person_id: str | None = None
        self._last_egress_camera: str | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to egress events."""
        await super().async_added_to_hass()
        self.hass.bus.async_listen("ura_person_egress_event", self._handle_egress_event)

    @callback
    def _handle_egress_event(self, event) -> None:
        """Handle an egress event from the bus."""
        if event.data.get("direction") != "entry":
            return
        ts_str = event.data.get("timestamp")
        if ts_str:
            self._last_entry = dt_util.parse_datetime(ts_str) or dt_util.now()
        else:
            self._last_entry = dt_util.now()
        self._last_person_id = event.data.get("person_id") or "unidentified"
        self._last_egress_camera = event.data.get("egress_camera")
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> datetime | None:
        """Return timestamp of last entry."""
        return self._last_entry

    @property
    def extra_state_attributes(self) -> dict:
        """Return entry details."""
        return {
            "person_id": self._last_person_id,
            "egress_camera": self._last_egress_camera,
        }


class LastPersonExitSensor(AggregationEntity, SensorEntity):
    """Timestamp of the most recent confirmed exit event."""

    _attr_icon = "mdi:account-arrow-left"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_last_person_exit"
        self._attr_name = "Last Person Exit"
        self._last_exit: datetime | None = None
        self._last_person_id: str | None = None
        self._last_egress_camera: str | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to egress events."""
        await super().async_added_to_hass()
        self.hass.bus.async_listen("ura_person_egress_event", self._handle_egress_event)

    @callback
    def _handle_egress_event(self, event) -> None:
        """Handle an egress event from the bus."""
        if event.data.get("direction") != "exit":
            return
        ts_str = event.data.get("timestamp")
        if ts_str:
            self._last_exit = dt_util.parse_datetime(ts_str) or dt_util.now()
        else:
            self._last_exit = dt_util.now()
        self._last_person_id = event.data.get("person_id") or "unidentified"
        self._last_egress_camera = event.data.get("egress_camera")
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> datetime | None:
        """Return timestamp of last exit."""
        return self._last_exit

    @property
    def extra_state_attributes(self) -> dict:
        """Return exit details."""
        return {
            "person_id": self._last_person_id,
            "egress_camera": self._last_egress_camera,
        }


class UnidentifiedPersonsSensor(AggregationEntity, SensorEntity):
    """House-level unidentified persons — camera sees them but BLE can't identify.

    Uses house-level camera count (PersonCensus) minus BLE identified count.
    Not per-zone: per-zone camera data does not exist in v3.5.1 Slim.
    """

    _attr_icon = "mdi:account-question"
    _attr_native_unit_of_measurement = "persons"
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_unidentified_persons"
        self._attr_name = "Unidentified Persons"

    @property
    def native_value(self) -> int | None:
        """Return count of unidentified persons (camera total minus BLE identified)."""
        census_state = self.hass.states.get(
            "sensor.universal_room_automation_persons_in_house"
        )
        if not census_state:
            return None
        try:
            camera_total = int(float(census_state.state))
        except (ValueError, TypeError):
            return None

        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if not person_coordinator:
            return None
        ble_identified = sum(
            1 for p in person_coordinator.data.values()
            if p.get("location") not in (None, "unknown", "away")
        )

        return max(0, camera_total - ble_identified)

    @property
    def extra_state_attributes(self) -> dict:
        """Return source details."""
        census_state = self.hass.states.get(
            "sensor.universal_room_automation_persons_in_house"
        )
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        camera_total = None
        ble_identified = None
        if census_state:
            try:
                camera_total = int(float(census_state.state))
            except (ValueError, TypeError):
                pass
        if person_coordinator:
            ble_identified = sum(
                1 for p in person_coordinator.data.values()
                if p.get("location") not in (None, "unknown", "away")
            )
        return {
            "camera_total": camera_total,
            "ble_identified": ble_identified,
            "data_scope": "house_level",
            "note": "Per-zone unidentified count deferred until per-zone camera data available",
        }


# ============================================================================
# v3.6.0 Domain Coordinator Sensors
# ============================================================================


class CoordinatorManagerSensor(AggregationEntity, SensorEntity):
    """Sensor showing Coordinator Manager status (running/stopped).

    Entity: sensor.ura_coordinator_manager
    Device: URA: Coordinator Manager
    Category: diagnostic
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:robot"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator manager sensor."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_coordinator_manager"
        self._attr_name = "Coordinator Manager"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> str:
        """Return the manager status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        return manager.get_overall_status()

    @property
    def extra_state_attributes(self) -> dict:
        """Return coordinator details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        return {
            "coordinators_registered": len(manager.coordinators),
            "coordinators_active": sum(
                1 for c in manager.coordinators.values() if c.enabled
            ),
            "decisions_today": manager.decisions_today,
            "conflicts_resolved_today": manager.conflicts_resolved_today,
        }


class URAMemoryStatusSensor(AggregationEntity, SensorEntity):
    """Hierarchical Memory MVP Stage 1 diagnostic sensor.

    Entity: sensor.ura_memory_status
    Device: URA: Coordinator Manager
    Category: diagnostic

    State: total episode count (cached — refreshed on the 5-min baseline
    fold and on episode insert). Attributes surface the writer's stats
    so operators can watch write volume BEFORE flipping the allowlist
    to house-wide (write-flood postmortem).
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:database-search"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_memory_status"
        self._attr_name = "Memory Status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )
        # Cached counts (updated by _refresh; kept cheap for
        # extra_state_attributes reads on HA polling).
        self._episode_total = 0
        self._episodes_by_type: dict = {}
        self._facts_count = 0
        self._baseline_row_count = 0

    async def _refresh(self) -> None:
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is None:
            return
        # LOW B9: use the public read-only accessor — never touch db._db()
        # (write queue) or db._db_read() (crossing a private) from a
        # diagnostic sensor. See database.get_memory_status_counts.
        try:
            counts = await db.get_memory_status_counts()
            self._episodes_by_type = counts.get("episodes_by_type") or {}
            self._episode_total = int(counts.get("episode_total", 0))
            self._facts_count = int(counts.get("facts_count", 0))
            self._baseline_row_count = int(
                counts.get("baseline_row_count", 0),
            )
        except Exception:  # noqa: BLE001
            pass

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from datetime import timedelta as _timedelta  # noqa: PLC0415
        from homeassistant.helpers.event import (  # noqa: PLC0415
            async_track_time_interval,
        )
        # Kick an immediate refresh + a 5-min cadence tick.
        await self._refresh()

        async def _tick(_now):
            await self._refresh()
            self.async_write_ha_state()

        self._unsub_refresh = async_track_time_interval(
            self.hass, _tick, _timedelta(minutes=5),
        )

    async def async_will_remove_from_hass(self) -> None:
        unsub = getattr(self, "_unsub_refresh", None)
        if unsub is not None:
            unsub()
        await super().async_will_remove_from_hass()

    @property
    def native_value(self) -> int:
        return self._episode_total

    @property
    def extra_state_attributes(self) -> dict:
        from .const import (
            MEMORY_BASELINE_ALLOWLIST,
            MEMORY_BASELINE_WRITER_ENABLED,
        )
        from .memory_baseline import _stats  # noqa: PLC0415
        stats = _stats(self.hass)
        return {
            "episodes_by_type": dict(self._episodes_by_type),
            "facts_count": self._facts_count,
            "baseline_row_count": self._baseline_row_count,
            "baseline_last_fold": stats.get("last_fold"),
            "baseline_rows_written_last_cycle": stats.get(
                "rows_written_last_cycle", 0,
            ),
            "baseline_writer_enabled": bool(
                MEMORY_BASELINE_WRITER_ENABLED,
            ),
            "baseline_allowlist": list(MEMORY_BASELINE_ALLOWLIST),
        }


class HousePolicySensor(AggregationEntity, SensorEntity):
    """House-State Rung 2a (v5.39.0) — CM-device house policy diagnostic.

    Entity: sensor.ura_coordinator_manager_house_policy
    Device: URA: Coordinator Manager
    Category: diagnostic

    INV-1: exposes which state-driven policies are currently active and
    the most recent state-driven action taken by any coordinator. Reads
    ``CoordinatorManager.house_policy`` (recomputed live). Updates via
    ``SIGNAL_HOUSE_POLICY_UPDATE``.

    State: comma-joined ``active_policies`` list (or "idle" when empty).
    Attrs: ``active_policies`` (list), ``last_state_driven_action`` (dict).
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:home-automation"
    # B-M4 fix-up: AggregationEntity does NOT set _attr_should_poll; the
    # SensorEntity base defaults to True. This sensor is signal-driven
    # (SIGNAL_HOUSE_POLICY_UPDATE) — polling would waste HA scheduler ticks.
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the house-policy sensor."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_coordinator_manager_house_policy"
        self._attr_name = "House Policy"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> str:
        """Return a compact status string.

        "idle" when no state-driven policies are active; otherwise the
        comma-joined active-policies list.
        """
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        try:
            policy = manager.house_policy
        except Exception:
            return "error"
        active = policy.get("active_policies") or []
        if not active:
            return "idle"
        # C-3 fix-up: bound the state string (HA state length limit is 255;
        # be defensive well below that). Full list stays in attrs.
        joined = ",".join(active)
        if len(joined) > 240:
            return f"{len(active)} policies active"
        return joined

    @property
    def extra_state_attributes(self) -> dict:
        """Return the full policy snapshot."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {"status": "not_initialized"}
        try:
            return manager.house_policy
        except Exception:
            return {"status": "error"}

    async def async_added_to_hass(self) -> None:
        """Subscribe to policy updates."""
        await super().async_added_to_hass()
        # B-LOW-2 fix-up: imports hoisted to module top — signals.py is a
        # leaf module (no circular-import risk), async_dispatcher_connect
        # is a stable HA API.
        self.async_on_remove(
            _hs_async_dispatcher_connect(
                self.hass, SIGNAL_HOUSE_POLICY_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle house-policy update signal."""
        self.async_schedule_update_ha_state()


class URAStuckSignalWatchdogSensor(AggregationEntity, SensorEntity):
    """House-level diagnostic sensor for the stuck-signal watchdog (v5.36.0 D1).

    State: total count of currently-active suspect signals across the three
    detector surfaces (stuck cameras + per-room stuck sensors + frozen
    trackers).

    Attributes surface the raw per-surface lists plus a per-kind NM emit
    ledger. All reads are cheap sync accessors (no DB, no service calls) —
    the sensor property is called on every state change of any subscribed
    entity and must remain O(rooms). The emit ledger is RAM-only and
    resets on HA restart.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:radar"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the stuck-signal watchdog sensor."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_stuck_signal_watchdog"
        self._attr_name = "Stuck Signal Watchdog"
        # Register on the Coordinator Manager device so it lives with the
        # other house-level diagnostic sensors (CoordinatorManagerSensor,
        # HouseStateSensor, etc.).
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    def _collect(self) -> tuple[list, dict, list]:
        """Gather (stuck_cameras, stuck_sensors_by_room, frozen_trackers).

        All three surfaces are pulled via public accessors — no
        cross-module private-attr reach (B L-3). Each guarded so one
        missing coordinator does not blank the sensor.
        """
        stuck_cameras: list = []
        stuck_sensors: dict = {}
        frozen_trackers: list = []
        try:
            census = self.hass.data.get(DOMAIN, {}).get("census")
            if census is not None and hasattr(census, "get_stuck_cameras"):
                stuck_cameras = list(census.get_stuck_cameras())
        except Exception:  # noqa: BLE001
            _LOGGER.debug("stuck_signal_watchdog: census read failed", exc_info=True)
        try:
            from .aggregation import _get_room_coordinators
            for coord in _get_room_coordinators(self.hass):
                try:
                    kinds = coord.get_stuck_sensor_kinds()
                except Exception:  # noqa: BLE001
                    continue
                if not kinds:
                    continue
                room = coord.entry.data.get("room_name", "unknown")
                stuck_sensors[room] = dict(kinds)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("stuck_signal_watchdog: room sweep failed", exc_info=True)
        try:
            person = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
            if person is not None and hasattr(person, "get_frozen_trackers"):
                frozen_trackers = list(person.get_frozen_trackers())
        except Exception:  # noqa: BLE001
            _LOGGER.debug("stuck_signal_watchdog: person read failed", exc_info=True)
        return stuck_cameras, stuck_sensors, frozen_trackers

    @property
    def native_value(self) -> int:
        """Return total count of currently-active suspect signals."""
        cams, sensors_by_room, frozen = self._collect()
        sensor_count = sum(len(v) for v in sensors_by_room.values())
        return len(cams) + sensor_count + len(frozen)

    @property
    def extra_state_attributes(self) -> dict:
        """Return per-surface breakdown + per-kind NM emit ledger."""
        cams, sensors_by_room, frozen = self._collect()
        stats: dict = {}
        try:
            from .domain_coordinators._stuck_signal_nm import get_emit_stats
            stats = get_emit_stats()
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "stuck_signal_watchdog: emit stats read failed", exc_info=True,
            )
        # Split ledger into per-kind ISO timestamps + fires_today counts
        # (the requested attr shape).
        last_fired = {k: v.get("last_fired") for k, v in stats.items()}
        fires_today = {k: int(v.get("fires_today", 0)) for k, v in stats.items()}
        return {
            "stuck_cameras": cams,
            "stuck_sensors": sensors_by_room,
            "frozen_trackers": frozen,
            "last_fired": last_fired,
            "fires_today": fires_today,
            "ledger_note": (
                "last_fired / fires_today are RAM-only and reset on HA restart"
            ),
        }


class HouseStateSensor(AggregationEntity, SensorEntity):
    """Sensor showing the current house state.

    Entity: sensor.ura_house_state
    Device: URA: Coordinator Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-account"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the house state sensor."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_house_state"
        self._attr_name = "House State"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> str:
        """Return the current house state."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "away"
        return manager.house_state.value

    @property
    def extra_state_attributes(self) -> dict:
        """Return state machine details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        return manager.house_state_machine.to_dict()


class CoordinatorSummarySensor(AggregationEntity, SensorEntity):
    """Summary sensor showing overall coordinator status.

    Entity: sensor.ura_coordinator_summary
    Device: URA: Coordinator Manager
    State: all_clear / advisory / alert / critical
    Attributes: per-coordinator status
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:robot"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator summary sensor."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_coordinator_summary"
        self._attr_name = "Coordinator Summary"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> str:
        """Return overall status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        if not manager.is_running:
            return "stopped"
        # In C0, no coordinators are registered yet — always all_clear
        return "all_clear"

    @property
    def extra_state_attributes(self) -> dict:
        """Return per-coordinator summary."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        return manager.get_summary()


# ============================================================================
# v3.6.0-c1: Presence Coordinator Sensors
# ============================================================================


class PresenceHouseStateSensor(AggregationEntity, SensorEntity):
    """Authoritative house state sensor on the Presence Coordinator device.

    Entity: sensor.ura_presence_house_state
    Device: URA: Presence Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-account"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_presence_house_state"
        self._attr_name = "Presence House State"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> str:
        """Return the current house state."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "away"
        return manager.house_state.value

    @property
    def extra_state_attributes(self) -> dict:
        """Return state machine details and presence diagnostics."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        attrs = manager.house_state_machine.to_dict()
        presence = manager.coordinators.get("presence")
        if presence is not None:
            attrs["confidence"] = round(presence.confidence, 2)
            attrs["census_count"] = presence.census_count
            # v4.7.14: Person-tracker veto diagnostics. tracked_persons_count
            # is the RAW number of configured person.* trackers seen by
            # person_coordinator (pre-v4.7.14.1 semantic preserved per
            # fix-up A-M2). all_tracked_persons_away True means every TRUSTED
            # one is reporting away (drives the AWAY-state veto in
            # StateInferenceEngine.infer()).
            #
            # v4.7.14.1 fix-up A-M2: expose BOTH the raw count and the new
            # post-H2/H3-filter trusted count, plus the exclusion-reason map.
            # Without this dual exposure operators with 4 configured persons +
            # 1 phone_left_behind would see `tracked_persons_count = 3` and
            # misdiagnose person_coordinator dropout instead of the
            # phone-left-behind diagnostic firing.
            attrs["tracked_persons_count"] = getattr(
                presence, "_tracked_persons_count", 0
            )
            attrs["tracked_persons_count_trusted"] = getattr(
                presence, "_tracked_persons_count_trusted", 0
            )
            attrs["excluded_persons"] = dict(
                getattr(presence, "_excluded_persons", {}) or {}
            )
            attrs["all_tracked_persons_away"] = getattr(
                presence, "_all_tracked_persons_away", False
            )
            # v5.7.0 WS-A diagnostics:
            #   veto_path: which AWAY-veto limb most recently fired —
            #       "none" / "active" / "lost_admitted". Lets operators tell
            #       at a glance whether path α (v4.7.14) or path β (v5.7.0)
            #       drove the last AWAY transition (or none).
            #   lost_away_persons: the subset of the path-β denominator
            #       admitted via the LOST/STALE+away relaxation. Empty
            #       under v4.7.14 baseline.
            #   lost_away_grace_remaining_s: seconds remaining on the
            #       oldest LOST-since stamp before path β may fire. None
            #       when no LOST persons are present.
            #   outdoor_zones: zone_names flagged CONF_ZONE_IS_OUTDOOR;
            #       excluded from the WS-A4 indoor-occupancy aggregation
            #       that gates path β.
            attrs["veto_path"] = str(getattr(presence, "_veto_path", "none"))
            attrs["lost_away_persons"] = list(
                getattr(presence, "_lost_away_persons", []) or []
            )
            _grace_rem = getattr(presence, "_lost_away_grace_remaining_s", None)
            attrs["lost_away_grace_remaining_s"] = (
                int(_grace_rem) if _grace_rem is not None else None
            )
            attrs["outdoor_zones"] = list(
                getattr(presence, "_outdoor_zones", []) or []
            )
            # v4.7.15 D5: Mirror signal_consensus dimension as attributes.
            # Same value also published as dedicated sensor.ura_signal_consensus_confidence;
            # operators get both surfaces.
            _consensus = round(getattr(presence, "_signal_consensus", 1.0), 2)
            attrs["signal_consensus"] = _consensus
            attrs["signal_consensus_band"] = _signal_consensus_band(_consensus)
            attrs["signal_consensus_inputs"] = dict(
                getattr(presence, "_signal_consensus_inputs", {}) or {}
            )
            _low_since = getattr(presence, "_consensus_low_since", None)
            attrs["consensus_low_since"] = (
                _low_since.isoformat() if _low_since is not None else None
            )
            # v4.7.15 D1/D3: shared-veto helper diagnostics.
            _last_veto = getattr(presence, "_last_veto_decision", None)
            if _last_veto is not None:
                attrs["last_veto_decision"] = {
                    "fired": getattr(_last_veto, "fired", False),
                    "confidence": getattr(_last_veto, "confidence", 0.0),
                    "reason": getattr(_last_veto, "reason", ""),
                    "scope": getattr(_last_veto, "scope", ""),
                }
            else:
                attrs["last_veto_decision"] = {
                    "fired": False, "confidence": 0.0, "reason": "", "scope": "",
                }
            # v4.7.15 D3: WAKING-gate diagnostic counter.
            attrs["wake_blocked_ticks"] = getattr(presence, "_wake_blocked_ticks", 0)
            # B-2026-08-03-2 fix-up MED-B: arriving re-arm cooldown counters
            # + active state. `arriving_rearm_active` is a bool derived from
            # `_arriving_rearm_until > 0` (0.0 = inactive/expired).
            attrs["arriving_rearm_suppressed"] = getattr(
                presence, "_arriving_rearm_suppressed", 0
            )
            attrs["arriving_rearm_bypassed"] = getattr(
                presence, "_arriving_rearm_bypassed", 0
            )
            attrs["arriving_rearm_active"] = bool(
                getattr(presence, "_arriving_rearm_until", 0.0) > 0.0
            )
            # v4.7.18.1 D2: Daytime wake-backstop diagnostic counter.
            attrs["wake_backstop_fires"] = getattr(presence, "_wake_backstop_fires", 0)
            # Cold-boot away-actuation storm mitigation — gate observability.
            # `boot_settle_done` flips True once the gate releases (or at
            # setup-time on a reload). `boot_settle_release_reason` is one
            # of: pending, real_input, ha_started, timeout, not_cold_boot.
            # `boot_settle_presence_suppressed` counts dispatch sites
            # short-circuited by Gate 1; `boot_settle_hvac_suppressed`
            # counts HVAC first-decision-cycle calls short-circuited by
            # Gate 2. Both counters let the operator tell which gate
            # actually caught the storm so the redundant one can be pruned
            # in a later cycle.
            attrs["boot_settle_done"] = bool(
                getattr(presence, "_boot_settle_done", False)
            )
            attrs["boot_settle_release_reason"] = str(
                getattr(presence, "_boot_settle_release_reason", "pending")
            )
            attrs["boot_settle_presence_suppressed"] = int(
                getattr(presence, "_boot_settle_presence_suppressed", 0)
            )
            # HVAC counter lives on the HVAC coordinator; pull defensively.
            _hvac_suppressed = 0
            try:
                _mgr = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
                if _mgr is not None:
                    _hvac = _mgr.coordinators.get("hvac")
                    if _hvac is not None:
                        _hvac_suppressed = int(
                            getattr(_hvac, "_boot_settle_hvac_suppressed", 0)
                        )
            except Exception:  # noqa: BLE001 — defensive: stale CM / early boot
                _hvac_suppressed = 0
            attrs["boot_settle_hvac_suppressed"] = _hvac_suppressed
            # Provenance-split cycle (D5): per-zone breakdown + per-room
            # provenance/fan diagnostic rollup. `tier1_provenance_breakdown`
            # is a {kind -> int} map of how many rooms in this zone are
            # currently positive for each Tier-1 kind. `fan_interference_rooms`
            # is the per-tick D3 flag-list scoped to this zone.
            attrs["zones"] = {
                name: {
                    "mode": tracker.mode,
                    "signal_tiers": {
                        "room_sensors": getattr(tracker, '_has_room_sensors', False),
                        "camera_sensors": getattr(tracker, '_has_camera_sensors', False),
                        "ble_sensors": getattr(tracker, '_has_ble_sensors', False),
                    },
                    "cameras_active": sum(
                        1 for v in getattr(tracker, '_camera_occupied', {}).values() if v
                    ),
                    "last_face_recognized": getattr(tracker, '_last_face_recognized', ""),
                    "last_face_time": (
                        t.isoformat() if (t := getattr(tracker, '_last_face_time', None)) else None
                    ),
                    "tier1_provenance_breakdown": _zone_provenance_breakdown(tracker),
                    "fan_interference_rooms": sorted(
                        rn for rn in (
                            _signal_consensus_get_list(
                                presence, "fan_interference_rooms",
                            )
                        )
                        if rn in tracker.room_names
                    ),
                    "fan_on_rooms": sorted(
                        getattr(tracker, "_fan_on_rooms", set()) or set()
                    ),
                }
                for name, tracker in presence.zone_trackers.items()
            }
            # House-wide rollup — was any room flagged this tick?
            attrs["fan_interference_active"] = bool(
                (getattr(presence, "_signal_consensus_inputs", {}) or {}).get(
                    "fan_interference_active", False,
                )
            )
        return attrs


class HouseStateConfidenceSensor(AggregationEntity, SensorEntity):
    """Confidence of the inferred house state (0.0-1.0).

    Entity: sensor.ura_house_state_confidence
    Device: URA: Presence Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:gauge"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_house_state_confidence"
        self._attr_name = "House State Confidence"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> float | None:
        """Return the confidence percentage."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        presence = manager.coordinators.get("presence")
        if presence is None:
            return None
        return round(presence.confidence, 2)


def _zone_provenance_breakdown(tracker) -> dict:
    """Provenance-split cycle (D5) helper: per-zone Tier-1 kind counts.

    Returns ``{kind: count_of_rooms_with_that_kind_True}`` for every
    kind in :data:`TIER1_KINDS` plus a legacy ``"tier1"`` sentinel
    bucket (A-LOW-2 review fix-up — rooms written via the back-compat
    ``kind=None`` path land in the ``"tier1"`` slot and would otherwise
    be invisible on this diagnostic surface).
    Always returns a stable shape so operator dashboards can pin
    attribute names.
    """
    from .const import TIER1_KINDS  # function-local — Bug Class #34
    out = {k: 0 for k in TIER1_KINDS}
    out["tier1"] = 0
    try:
        for _room, kinds in getattr(tracker, "_room_provenance", {}).items():
            for k in TIER1_KINDS:
                if kinds.get(k, False):
                    out[k] += 1
            if kinds.get("tier1", False):
                out["tier1"] += 1
    except Exception:  # noqa: BLE001 — defensive
        pass
    return out


def _signal_consensus_get_list(presence, key: str) -> list:
    """Safe accessor for ``presence._signal_consensus_inputs[key]`` as a list."""
    try:
        inputs = getattr(presence, "_signal_consensus_inputs", {}) or {}
        val = inputs.get(key, [])
        if isinstance(val, list):
            return val
    except Exception:  # noqa: BLE001
        pass
    return []


def _signal_consensus_band(value: float) -> str:
    """v4.7.15 D5: decorative band label for signal_consensus.

    Thresholds chosen to align with D6 gate thresholds: high >= 0.85 (steady),
    moderate >= 0.6 (compliance-defer threshold), low >= 0.3, else degraded.
    """
    if value >= 0.85:
        return "high"
    if value >= 0.6:
        return "moderate"
    if value >= 0.3:
        return "low"
    return "degraded"


class SignalConsensusConfidenceSensor(AggregationEntity, SensorEntity):
    """v4.7.15 D5: input-agreement confidence sensor.

    DISTINCT from sensor.ura_house_state_confidence (the engine's certainty
    in the chosen state). signal_consensus tracks whether the raw INPUTS
    agree with each other at the current tick — a leading indicator that
    can drop before the engine's output confidence does.

    Scale: 1.0 = inputs in perfect agreement (steady state); 0.0 = severely
    degraded (multiple Bug Class #48 shape disagreements).

    Entity: sensor.ura_signal_consensus_confidence
    Device: URA: Presence Coordinator

    Bug Class #47-safe: lazy read at native_value time. Does NOT persist into
    entry.options or registry; the canonical store is presence._signal_consensus
    updated each _run_inference tick.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:scale-balance"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_signal_consensus_confidence"
        self._attr_name = "Signal Consensus Confidence"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> float | None:
        """Lazy read of presence._signal_consensus."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        presence = manager.coordinators.get("presence")
        if presence is None:
            return None
        return round(getattr(presence, "_signal_consensus", 1.0), 2)

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the per-component disagreement snapshot + decorative band."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        presence = manager.coordinators.get("presence")
        if presence is None:
            return {}
        value = round(getattr(presence, "_signal_consensus", 1.0), 2)
        inputs = getattr(presence, "_signal_consensus_inputs", {}) or {}
        low_since = getattr(presence, "_consensus_low_since", None)
        return {
            "consensus_band": _signal_consensus_band(value),
            "signal_consensus_inputs": dict(inputs),
            "consensus_low_since": (
                low_since.isoformat() if low_since is not None else None
            ),
        }


# ============================================================================
# build/pc-observability: attribute-to-sensor promotions on the Presence
# Coordinator device. Each new sensor lazy-reads the SAME underlying counter/
# state on the presence coordinator that the giant house-state sensor's
# attrs payload already exposes — additive only, no attrs are removed from
# `sensor.ura_presence_house_state`. Sources cited on each class.
# ============================================================================


class PresenceCensusCountSensor(AggregationEntity, SensorEntity):
    """People count from the camera-census pipeline.

    Promotes the ``census_count`` attribute on
    ``sensor.ura_presence_house_state`` (sensor.py:~4566) to a graphable
    integer sensor. Reads ``PresenceCoordinator._census_count`` — same
    field the attr reads.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_presence_census_count"
        # Operator-directive: friendly names in plain English, geek term in parens.
        self._attr_name = "People Home (census)"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> int | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        presence = manager.coordinators.get("presence")
        if presence is None:
            return None
        try:
            return int(getattr(presence, "_census_count", 0))
        except (TypeError, ValueError):
            return None


class PresenceWakeBlockedTicksSensor(AggregationEntity, SensorEntity):
    """Monotonic counter of WAKING-transition ticks blocked by the sustained-signal gate.

    Promotes the ``wake_blocked_ticks`` attribute on
    ``sensor.ura_presence_house_state`` (sensor.py:~4644) to a
    total_increasing sensor. Reads ``PresenceCoordinator._wake_blocked_ticks``.
    Primary diagnostic for "why is the house still SLEEP at 10am".
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:sleep-off"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_presence_wake_blocked_ticks"
        self._attr_name = "Mornings Blocked From Waking"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> int | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        presence = manager.coordinators.get("presence")
        if presence is None:
            return None
        try:
            return int(getattr(presence, "_wake_blocked_ticks", 0))
        except (TypeError, ValueError):
            return None


class PresenceWakeBackstopFiresSensor(AggregationEntity, SensorEntity):
    """Monotonic counter of wake-backstop safety-valve fires.

    Promotes the ``wake_backstop_fires`` attribute on
    ``sensor.ura_presence_house_state`` (sensor.py:~4658). Reads
    ``PresenceCoordinator._wake_backstop_fires``. Any non-zero rate is
    a sev-2 signal that some upstream WAKING gate regressed — NM anomaly
    is emitted at each fire site (presence.py wake-backstop block).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-octagon"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_presence_wake_backstop_fires"
        self._attr_name = "Wake Safety Valve Fires"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> int | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        presence = manager.coordinators.get("presence")
        if presence is None:
            return None
        try:
            return int(getattr(presence, "_wake_backstop_fires", 0))
        except (TypeError, ValueError):
            return None


class PresenceArrivingRearmSuppressedSensor(AggregationEntity, SensorEntity):
    """Monotonic counter of ARRIVING attempts suppressed by the flap-guard cooldown.

    Promotes the ``arriving_rearm_suppressed`` attribute on
    ``sensor.ura_presence_house_state`` (sensor.py:~4648). Reads
    ``PresenceCoordinator._arriving_rearm_suppressed``. Flap-detector KPI
    (2026-08-03 patio-flap incident).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-sand"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_presence_arriving_rearm_suppressed"
        self._attr_name = "Arrival Re-Alerts Muted (flap guard)"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> int | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        presence = manager.coordinators.get("presence")
        if presence is None:
            return None
        try:
            return int(getattr(presence, "_arriving_rearm_suppressed", 0))
        except (TypeError, ValueError):
            return None


class PresenceArrivingRearmBypassedSensor(AggregationEntity, SensorEntity):
    """Monotonic counter of cooldown bypasses due to new (non-flap) evidence.

    Promotes the ``arriving_rearm_bypassed`` attribute on
    ``sensor.ura_presence_house_state`` (sensor.py:~4651). Reads
    ``PresenceCoordinator._arriving_rearm_bypassed``. Sibling to the
    suppressed counter; ratio bypassed/suppressed reveals cooldown
    correctness (mostly-bypassed = cooldown is too eager).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-check"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_presence_arriving_rearm_bypassed"
        self._attr_name = "Arrival Re-Alerts Skipped (real arrivals)"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> int | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        presence = manager.coordinators.get("presence")
        if presence is None:
            return None
        try:
            return int(getattr(presence, "_arriving_rearm_bypassed", 0))
        except (TypeError, ValueError):
            return None


class PresenceDiagnosticSensor(AggregationEntity, SensorEntity):
    """Diagnostic COPY of dark presence-internals (disabled by default).

    Operator directive (AUDIT §Operator adjudication #3): ADDITIVE ONLY —
    this sensor is a COPY surface; nothing is removed from
    ``sensor.ura_presence_house_state``.

    Exposes as attrs:
      - ``last_veto_decision`` (dict) — from ``_last_veto_decision``
      - ``signal_consensus_inputs`` (dict) — from ``_signal_consensus_inputs``
      - ``excluded_persons`` (dict) — from ``_excluded_persons``
      - ``zone_verdicts`` (dict) — from the DARK ``_v4716_zone_verdicts``
        (presence.py:~1383) — computed each cycle, previously never
        surfaced anywhere.

    Entity is disabled_by_default=True and entity_category=DIAGNOSTIC so it
    only lands on the device page when the operator opts in.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:magnify-scan"
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # C-L5: opt-in only. When enabled, this sensor writes state on every
    # inference-driven refresh; the recorder cost is non-trivial because
    # the attrs (last_veto_decision, signal_consensus_inputs, zone_verdicts)
    # can be O(rooms) each. Left OFF by default; operator opts in during
    # active diagnosis and disables again afterwards. Explicit
    # _attr_should_poll = False (documented, matches AggregationEntity
    # push-only behavior — no recorder poll cost).
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_presence_diagnostics"
        self._attr_name = "Presence Diagnostics"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> str | None:
        """State = the veto-decision scope, useful as an at-a-glance token."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        presence = manager.coordinators.get("presence")
        if presence is None:
            return None
        _lv = getattr(presence, "_last_veto_decision", None)
        # A-LOW-5: None when nothing has been computed yet (not empty string).
        if _lv is None:
            return None
        _scope = getattr(_lv, "scope", None)
        return str(_scope) if _scope else None

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        presence = manager.coordinators.get("presence")
        if presence is None:
            return {}
        _lv = getattr(presence, "_last_veto_decision", None)
        if _lv is not None:
            last_veto_decision = {
                "fired": bool(getattr(_lv, "fired", False)),
                "confidence": float(getattr(_lv, "confidence", 0.0)),
                "reason": str(getattr(_lv, "reason", "")),
                "scope": str(getattr(_lv, "scope", "")),
            }
        else:
            last_veto_decision = {
                "fired": False, "confidence": 0.0, "reason": "", "scope": "",
            }
        try:
            zone_verdicts = dict(
                getattr(presence, "_v4716_zone_verdicts", {}) or {}
            )
        except Exception:  # noqa: BLE001 — defensive: stale coord data
            zone_verdicts = {}
        # TRANSIT-DIAG-1 (2026-08-07): surface the transit-validator
        # Protect-sourced checkpoint map read-only on this existing
        # presence-diagnostic host (REUSED — no new sensor needed).
        # v5.60.0 shipped ``checkpoint_cameras_by_area`` as a Python attr
        # only; verifying it live required raising the log level. Now
        # exposed as attrs: ``checkpoint_cameras_by_area`` (mapping) and
        # ``protect_sourced_count`` (int). Purely additive; kill-switch
        # off yields an empty mapping / zero count.
        checkpoint_cameras_by_area: dict[str, list[str]] = {}
        protect_sourced_count = 0
        try:
            tv = self.hass.data.get(DOMAIN, {}).get("transit_validator")
            if tv is not None:
                # F4 (2026-08-07 fix-up cycle-4): route through the
                # validator's own helper so behavioral tests can
                # mutation-drill the population path without importing
                # sensor.py (which pulls the whole package). Fallback
                # to legacy in-line read if the helper is absent (e.g.
                # a stale coord instance mid-reload).
                _builder = getattr(tv, "build_diagnostic_attrs", None)
                if callable(_builder):
                    _payload = _builder() or {}
                    checkpoint_cameras_by_area = (
                        _payload.get("checkpoint_cameras_by_area") or {}
                    )
                    protect_sourced_count = int(
                        _payload.get("protect_sourced_count") or 0
                    )
                else:
                    raw = getattr(tv, "checkpoint_cameras_by_area", None) or {}
                    checkpoint_cameras_by_area = {
                        a: sorted(list(eids)) for a, eids in raw.items()
                    }
                    protect_sourced_count = sum(
                        len(v) for v in checkpoint_cameras_by_area.values()
                    )
        except Exception:  # noqa: BLE001 — defensive: transit_validator absent/torn down
            checkpoint_cameras_by_area = {}
            protect_sourced_count = 0
        return {
            "last_veto_decision": last_veto_decision,
            "signal_consensus_inputs": dict(
                getattr(presence, "_signal_consensus_inputs", {}) or {}
            ),
            "excluded_persons": dict(
                getattr(presence, "_excluded_persons", {}) or {}
            ),
            "zone_verdicts": zone_verdicts,
            "checkpoint_cameras_by_area": checkpoint_cameras_by_area,
            "protect_sourced_count": protect_sourced_count,
        }


class PresenceAnomalySensor(AggregationEntity, SensorEntity):
    """Presence anomaly status.

    Entity: sensor.ura_presence_anomaly
    Device: URA: Presence Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_presence_anomaly"
        self._attr_name = "Presence Anomaly"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> str:
        """Return the anomaly status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        presence = manager.coordinators.get("presence")
        if presence is None:
            return "disabled"
        if presence.anomaly_detector is None:
            return "not_configured"
        # Show learning status if not yet active
        learning = presence.anomaly_detector.get_learning_status()
        if hasattr(learning, 'value') and learning.value in ("insufficient_data", "learning"):
            return learning.value
        return presence.anomaly_detector.get_worst_severity().value

    @property
    def extra_state_attributes(self) -> dict:
        """v4.5.14: surface AnomalyDetector status summary (learning_status,
        metrics_active_ratio, per-metric sample counts) so dead-metric
        coverage is visible at a glance.
        """
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        presence = manager.coordinators.get("presence")
        if presence is None or presence.anomaly_detector is None:
            return {}
        return presence.anomaly_detector.get_status_summary()

    async def async_added_to_hass(self) -> None:
        """v4.5.20: subscribe to Presence coord's per-cycle refresh signal."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_PRESENCE_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_PRESENCE_ENTITIES_UPDATE, self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_schedule_update_ha_state()


class PresenceComplianceSensor(AggregationEntity, SensorEntity):
    """Presence compliance rate.

    Entity: sensor.ura_presence_compliance
    Device: URA: Presence Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_presence_compliance"
        self._attr_name = "Presence Compliance"
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def native_value(self) -> float:
        """Return the cached compliance rate (refreshed in async_update)."""
        return getattr(self, "_compliance_value", 100.0)

    async def async_update(self) -> None:
        """Refresh the compliance rate from the tracker (async DB read)."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        presence = manager.coordinators.get("presence")
        if presence is None or presence.compliance_tracker is None:
            return
        try:
            rate = await presence.compliance_tracker.get_compliance_rate("presence")
            self._compliance_value = round(rate * 100, 1) if rate is not None else 100.0
        except (AttributeError, TypeError):
            self._compliance_value = 100.0


# ============================================================================
# v4.6.9 D1: Presence Coordinator — Next-State Prediction Sensor
# ============================================================================


try:
    from enum import StrEnum as _StrEnum
except ImportError:
    from enum import Enum as _BaseEnum

    class _StrEnum(str, _BaseEnum):  # type: ignore[no-redef]
        """Python < 3.11 StrEnum backport."""


class _NextStateVocab(_StrEnum):
    """Bug Class #22: StrEnum for the next-state prediction vocabulary.

    Vocabulary matches the plan's PWA hook contract:
      home_day | home_night | away | sleep | guest | vacation | unknown
    """
    HOME_DAY = "home_day"
    HOME_NIGHT = "home_night"
    AWAY = "away"
    SLEEP = "sleep"
    GUEST = "guest"
    VACATION = "vacation"
    UNKNOWN = "unknown"


class PresenceNextStateSensor(AggregationEntity, SensorEntity):
    """Routine awareness next-state prediction sensor.

    Entity: sensor.ura_presence_coordinator_next_state
    Device: URA: Presence Coordinator
    State: predicted house state (home_day | home_night | away | sleep |
           guest | vacation | unknown)
    Attributes (flat, PWA-parseable):
      confidence: float (0.0-1.0)
      predicted_at_iso: str (ISO 8601 UTC)
      model: str (model id / version)
      current_state: str (current house state, for cross-check)
      transition_eta_minutes: int | null

    v4.6.9 D1: The Routine Awareness v4.6.0 cycle introduced regime shift
    *detection* (RegimeDetector, nightly batch) but not forward next-state
    prediction.  PresenceCoordinator.get_next_state_prediction() currently
    returns a placeholder_v0 shape (state="unknown", confidence=0.0).
    A real model is planned for v4.7.x.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:crystal-ball"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_next_state"
        self._attr_name = "Next State"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_prediction(self) -> dict | None:
        """Read the prediction from the presence coordinator.

        Bug Class #14 (config staleness): called on every populator access —
        never caches; always reads from the live coordinator.
        """
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return None
            presence = manager.coordinators.get("presence")
            if presence is None:
                return None
            return presence.get_next_state_prediction()
        except Exception:
            _LOGGER.debug(
                "PresenceNextStateSensor: error reading prediction", exc_info=True
            )
            return None

    @property
    def native_value(self) -> str:
        """Return the predicted next house state.

        Tier 2-DB Reviewer A H3 fix: return the vocabulary value "unknown"
        when prediction is unavailable — NOT the HA STATE_UNAVAILABLE constant.
        The HA constant ("unavailable") would be stored as a string state in
        the PWA's read path (useUraSensorState.state) and bypass the proper
        unavailable signalling. The PWA's hook maps "unknown" → unavailable=True
        via its state-vocab check.

        Bug Class #29: covers the null-model branch — never returns "—"/"N/A"/"".
        Bug Class #22: state value is validated against _NextStateVocab.
        """
        prediction = self._get_prediction()
        if prediction is None:
            return _NextStateVocab.UNKNOWN.value
        raw = prediction.get("state", "unknown")
        # Validate against vocabulary — default to "unknown" on bad value
        try:
            return _NextStateVocab(raw).value
        except ValueError:
            _LOGGER.debug(
                "PresenceNextStateSensor: unexpected state value %r — using unknown", raw
            )
            return _NextStateVocab.UNKNOWN.value

    @property
    def extra_state_attributes(self) -> dict:
        """Return flat PWA-parseable attribute dict.

        Bug Class #37 (stable attribute shape): keys are always present;
        null values use None (not absent keys).
        All values are JSON-serializable: float, str, int, or None.
        No Decimal, no datetime objects, no nested dicts.
        """
        prediction = self._get_prediction()
        if prediction is None:
            return {
                "confidence": 0.0,
                "predicted_at_iso": None,
                "model": None,
                "current_state": None,
                "transition_eta_minutes": None,
            }
        eta = prediction.get("transition_eta_minutes")
        return {
            "confidence": float(prediction.get("confidence", 0.0)),
            "predicted_at_iso": prediction.get("predicted_at_iso"),
            "model": prediction.get("model"),
            "current_state": prediction.get("current_state"),
            "transition_eta_minutes": int(eta) if eta is not None else None,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to house-state change signal for live updates.

        Bug Class #1 (coordinator lifecycle): super() called first; subscription
        cleaned up via async_on_remove (no untracked listeners).
        Bug Class #19 (untracked background tasks): no tasks created here.
        """
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_HOUSE_STATE_CHANGED
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HOUSE_STATE_CHANGED, self._handle_update,
            )
        )
        _LOGGER.debug("PresenceNextStateSensor: subscribed to SIGNAL_HOUSE_STATE_CHANGED")

    @callback
    def _handle_update(self, *args: Any) -> None:
        """Schedule a state refresh when house state changes."""
        self.async_schedule_update_ha_state()


class IntegrationHouseStateSensor(AggregationEntity, SensorEntity):
    """House state sensor duplicated on the URA integration device.

    Entity: sensor.ura_integration_house_state
    Device: Universal Room Automation (integration device)
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-account"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_integration_house_state"
        self._attr_name = "House State"
        # device_info inherited from AggregationEntity — integration device

    @property
    def native_value(self) -> str:
        """Return the current house state."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "away"
        return manager.house_state.value

    @property
    def extra_state_attributes(self) -> dict:
        """Return state machine details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        return manager.house_state_machine.to_dict()


# ============================================================================
# v3.6.0-c2: Safety Coordinator Sensors
# ============================================================================

# Helper for Safety device info
def _safety_device_info():
    """Return DeviceInfo for the Safety Coordinator device."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, "safety_coordinator")},
        name="URA: Safety Coordinator",
        manufacturer="Universal Room Automation",
        model="Safety Coordinator",
        sw_version=VERSION,
        via_device=(DOMAIN, "coordinator_manager"),
    )


class SafetyStatusSensor(AggregationEntity, SensorEntity):
    """Overall safety status sensor.

    Entity: sensor.ura_safety_status
    Device: URA: Safety Coordinator
    State: "normal" / "warning" / "alert" / "critical"
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-check"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_status"
        self._attr_name = "Safety Status"
        self._attr_device_info = _safety_device_info()

    @property
    def native_value(self) -> str:
        """Return the current safety status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "normal"
        safety = manager.coordinators.get("safety")
        if safety is None:
            return "normal"
        return safety.get_safety_status()

    @property
    def extra_state_attributes(self) -> dict:
        """Return safety status attributes."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        safety = manager.coordinators.get("safety")
        if safety is None:
            return {}

        # v3.6.0.3: Scope and detail
        hazards_detail = safety.get_all_hazards_detail()
        hazard_locations = set(h["location"] for h in hazards_detail)
        num_locations = len(hazard_locations)

        if not hazards_detail:
            scope = "clear"
        elif num_locations == 1:
            scope = "room"
        elif num_locations >= 3 or any(h["severity"] == "critical" for h in hazards_detail):
            scope = "house"
        else:
            scope = "multi_room"

        return {
            "active_hazards": len(safety.active_hazards),
            "sensors_monitored": safety.sensors_monitored,
            "last_check": dt_util.utcnow().isoformat(),
            # v3.6.0.3: Scope and detail
            "scope": scope,
            "worst_location": hazards_detail[0]["location"] if hazards_detail else None,
            "hazards": hazards_detail,
        }

    @property
    def icon(self) -> str:
        """Return icon based on safety status."""
        value = self.native_value
        if value == "critical":
            return "mdi:shield-alert"
        elif value == "alert":
            return "mdi:shield-alert-outline"
        elif value == "warning":
            return "mdi:shield-half-full"
        return "mdi:shield-check"

    async def async_added_to_hass(self) -> None:
        """Subscribe to safety entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle safety entity update signal."""
        self.async_schedule_update_ha_state()


class SafetyDiagnosticsSensor(AggregationEntity, SensorEntity):
    """Safety diagnostics sensor.

    Entity: sensor.ura_safety_diagnostics
    Device: URA: Safety Coordinator
    State: "healthy" / "degraded"
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:stethoscope"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_diagnostics"
        self._attr_name = "Safety Diagnostics"
        self._attr_device_info = _safety_device_info()

    @property
    def native_value(self) -> str:
        """Return the diagnostics health status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "degraded"
        safety = manager.coordinators.get("safety")
        if safety is None:
            return "degraded"
        return safety.get_diagnostics_status()

    @property
    def extra_state_attributes(self) -> dict:
        """Return diagnostics attributes."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        safety = manager.coordinators.get("safety")
        if safety is None:
            return {}
        return {
            "sensors_total": safety.sensors_monitored,
            "sensors_available": safety.sensors_monitored,
            "hazards_detected_24h": safety._hazards_detected_24h,
            "alerts_sent_24h": safety._alerts_sent_24h,
        }


class SafetyActiveHazardsSensor(AggregationEntity, SensorEntity):
    """Count of active safety hazards with full detail.

    v3.6.0.3: Glanceable entity — shows how many things are wrong.
    Entity: sensor.ura_safety_active_hazards
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:shield-check"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_active_hazards"
        self._attr_name = "Safety Active Hazards"
        self._attr_device_info = _safety_device_info()

    @property
    def native_value(self) -> int:
        """Return count of active hazards."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return 0
        safety = manager.coordinators.get("safety")
        if safety is None:
            return 0
        return len(safety.active_hazards)

    @property
    def icon(self) -> str:
        """Dynamic icon based on hazard count."""
        val = self.native_value
        if val == 0:
            return "mdi:shield-check"
        return "mdi:alert-octagon"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full hazard detail list."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {"hazards": []}
        safety = manager.coordinators.get("safety")
        if safety is None:
            return {"hazards": []}
        return {"hazards": safety.get_all_hazards_detail()}

    async def async_added_to_hass(self) -> None:
        """Subscribe to safety entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle safety entity update signal."""
        self.async_schedule_update_ha_state()


class SafetyAffectedRoomsSensor(AggregationEntity, SensorEntity):
    """Rooms with active safety hazards, grouped by zone.

    v3.6.0.6: Shows which rooms are affected and their zone grouping.
    Entity: sensor.ura_safety_affected_rooms
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_affected_rooms"
        self._attr_name = "Safety Affected Rooms"
        self._attr_device_info = _safety_device_info()

    @property
    def native_value(self) -> str:
        """Return comma-separated room names or 'clear'."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "clear"
        safety = manager.coordinators.get("safety")
        if safety is None:
            return "clear"
        status = safety.get_affected_rooms()
        rooms = status.get("affected_rooms", [])
        if not rooms:
            return "clear"
        return ", ".join(rooms)

    @property
    def icon(self) -> str:
        """Dynamic icon."""
        if self.native_value == "clear":
            return "mdi:home-check"
        return "mdi:home-alert"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return affected rooms detail."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {"affected_rooms": [], "affected_by_zone": {},
                    "room_count": 0, "zone_count": 0, "worst_room": None}
        safety = manager.coordinators.get("safety")
        if safety is None:
            return {"affected_rooms": [], "affected_by_zone": {},
                    "room_count": 0, "zone_count": 0, "worst_room": None}
        return safety.get_affected_rooms()

    async def async_added_to_hass(self) -> None:
        """Subscribe to safety entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle safety entity update signal."""
        self.async_schedule_update_ha_state()


class SafetyAnomalySensor(AggregationEntity, SensorEntity):
    """Safety anomaly status.

    Entity: sensor.ura_safety_anomaly
    Device: URA: Safety Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_anomaly"
        self._attr_name = "Safety Anomaly"
        self._attr_device_info = _safety_device_info()

    @property
    def native_value(self) -> str:
        """Return the anomaly status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        safety = manager.coordinators.get("safety")
        if safety is None:
            return "disabled"
        if safety.anomaly_detector is None:
            return "not_configured"
        learning = safety.anomaly_detector.get_learning_status()
        if hasattr(learning, 'value') and learning.value in ("insufficient_data", "learning"):
            return learning.value
        return safety.anomaly_detector.get_worst_severity().value

    @property
    def extra_state_attributes(self) -> dict:
        """v4.5.14: surface AnomalyDetector status summary."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        safety = manager.coordinators.get("safety")
        if safety is None or safety.anomaly_detector is None:
            return {}
        return safety.anomaly_detector.get_status_summary()

    async def async_added_to_hass(self) -> None:
        """v4.5.14: subscribe to safety entity updates for refresh."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_schedule_update_ha_state()


class SafetyComplianceSensor(AggregationEntity, SensorEntity):
    """Safety compliance rate.

    Entity: sensor.ura_safety_compliance
    Device: URA: Safety Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:check-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_compliance"
        self._attr_name = "Safety Compliance"
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_info = _safety_device_info()

    @property
    def native_value(self) -> float:
        """Return the cached compliance rate (refreshed in async_update)."""
        return getattr(self, "_compliance_value", 100.0)

    async def async_update(self) -> None:
        """Refresh the compliance rate from the tracker (async DB read)."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return
        safety = manager.coordinators.get("safety")
        if safety is None or safety.compliance_tracker is None:
            return
        try:
            rate = await safety.compliance_tracker.get_compliance_rate("safety")
            self._compliance_value = round(rate * 100, 1) if rate is not None else 100.0
        except (AttributeError, TypeError):
            self._compliance_value = 100.0


# ============================================================================
# v3.6.0-c3: Security Coordinator sensors
# ============================================================================


def _security_device_info():
    """Return DeviceInfo for the Security Coordinator device."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, "security_coordinator")},
        name="URA: Security Coordinator",
        manufacturer="Universal Room Automation",
        model="Security Coordinator",
        sw_version=VERSION,
        via_device=(DOMAIN, "coordinator_manager"),
    )


class SecurityArmedStateSensor(AggregationEntity, SensorEntity):
    """Current security armed state.

    Entity: sensor.ura_security_armed_state
    Device: URA: Security Coordinator
    State: "disarmed" / "armed_home" / "armed_away" / "armed_vacation"
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-lock"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_armed_state"
        self._attr_name = "Security Armed State"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self) -> str:
        """Return the current armed state."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "disarmed"
        security = manager.coordinators.get("security")
        if security is None:
            return "disarmed"
        return security.armed_state.value

    @property
    def extra_state_attributes(self) -> dict:
        """Return armed state attributes."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {"status": "not_initialized"}
        security = manager.coordinators.get("security")
        if security is None:
            return {"status": "disabled"}
        # House-State Rung 2a (v5.39.0): expose the per-coordinator
        # execution attr for state-driven arming. INV-1 per-coordinator
        # observability surface — the last auto-follow arm/would-arm.
        state_driven = getattr(security, "_state_driven_arming_last", {}) or {}
        return {
            "status": security.get_security_status(),
            "active_alert": security.active_alert,
            "state_driven_arming_last": dict(state_driven),
        }

    @property
    def icon(self) -> str:
        """Dynamic icon based on armed state."""
        value = self.native_value
        if value == "disarmed":
            return "mdi:shield-off-outline"
        if value == "armed_away":
            return "mdi:shield-lock"
        if value == "armed_vacation":
            return "mdi:shield-airplane"
        return "mdi:shield-home"

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_schedule_update_ha_state()


class SecurityLastEntrySensor(AggregationEntity, SensorEntity):
    """Last security entry event.

    Entity: sensor.ura_security_last_entry
    Device: URA: Security Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:door-open"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_last_entry"
        self._attr_name = "Security Last Entry"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self) -> str:
        """Return the last entry verdict."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "none"
        security = manager.coordinators.get("security")
        if security is None:
            return "none"
        event = security.last_entry_event
        return event.get("verdict", "none")

    @property
    def extra_state_attributes(self) -> dict:
        """Return last entry event details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        security = manager.coordinators.get("security")
        if security is None:
            return {}
        return security.last_entry_event

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_schedule_update_ha_state()


class SecurityAnomalySensor(AggregationEntity, SensorEntity):
    """Security anomaly status.

    Entity: sensor.ura_security_anomaly
    Device: URA: Security Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_anomaly"
        self._attr_name = "Security Anomaly"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self) -> str:
        """Return the anomaly status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        security = manager.coordinators.get("security")
        if security is None:
            return "disabled"
        return security.get_anomaly_status()

    @property
    def extra_state_attributes(self) -> dict:
        """v4.5.14: surface AnomalyDetector status summary."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        security = manager.coordinators.get("security")
        if security is None or security.anomaly_detector is None:
            return {}
        return security.anomaly_detector.get_status_summary()

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_schedule_update_ha_state()


class SecurityComplianceSensor(AggregationEntity, SensorEntity):
    """Security lock compliance rate.

    Entity: sensor.ura_security_compliance
    Device: URA: Security Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:lock-check"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_compliance"
        self._attr_name = "Security Compliance"
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self) -> float:
        """Return the lock compliance rate."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return 100.0
        security = manager.coordinators.get("security")
        if security is None:
            return 100.0
        summary = security.get_compliance_summary()
        return summary.get("compliance_rate", 100.0)

    @property
    def extra_state_attributes(self) -> dict:
        """Return compliance details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        security = manager.coordinators.get("security")
        if security is None:
            return {}
        return security.get_compliance_summary()

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_schedule_update_ha_state()


class SecurityOpenEntriesSensor(AggregationEntity, SensorEntity):
    """Count of currently-open configured doors/windows.

    Entity: sensor.ura_security_open_entries
    Device: URA: Security Coordinator
    State: integer count of open entries
    Attributes: list of open entries with entity_id, opened_at, open_minutes
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:door-open"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_open_entries"
        self._attr_name = "Security Open Entries"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self) -> int:
        """Return count of open entry sensors."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return 0
        security = manager.coordinators.get("security")
        if security is None:
            return 0
        return len(security.open_entries)

    @property
    def extra_state_attributes(self) -> dict:
        """Return open entry details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        security = manager.coordinators.get("security")
        if security is None:
            return {}
        return security.get_open_entries_snapshot()

    @property
    def icon(self) -> str:
        """Dynamic icon based on open count."""
        if self.native_value > 0:
            return "mdi:door-open"
        return "mdi:door-closed-lock"

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_schedule_update_ha_state()


class SecurityLastLockSweepSensor(AggregationEntity, SensorEntity):
    """Last lock sweep timestamp and results.

    Entity: sensor.ura_security_last_lock_sweep
    Device: URA: Security Coordinator
    State: ISO timestamp of last sweep (or "never")
    Attributes: found_unlocked, lock_actions_sent, unavailable, checks_today
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:lock-check"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_last_lock_sweep"
        self._attr_name = "Security Last Lock Sweep"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self):
        """Return the timestamp of the last lock sweep."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        security = manager.coordinators.get("security")
        if security is None:
            return None
        sweep = security.last_lock_sweep
        ts = sweep.get("timestamp")
        if not ts:
            return None
        try:
            # v4.2.9: Use parse_datetime for robust tz-aware parsing
            dt = dt_util.parse_datetime(ts)
            if dt is None:
                return None
            if dt.tzinfo is None:
                from datetime import timezone
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return lock sweep result details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        security = manager.coordinators.get("security")
        if security is None:
            return {}
        sweep = security.last_lock_sweep
        if not sweep:
            return {"status": "no_sweep_yet"}
        return {
            "found_unlocked": sweep.get("found_unlocked", []),
            "lock_actions_sent": sweep.get("lock_actions_sent", []),
            "unavailable": sweep.get("unavailable", []),
            "checks_today": sweep.get("checks_today", 0),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_schedule_update_ha_state()


class SecurityExpectedArrivalsSensor(AggregationEntity, SensorEntity):
    """Expected arrivals and authorized guests currently active.

    Entity: sensor.ura_security_expected_arrivals
    Device: URA: Security Coordinator
    State: count of active expected arrivals (geofence + manual)
    Attributes: expected_arrivals list, authorized_guests list
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-arrow-left"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_expected_arrivals"
        self._attr_name = "Security Expected Arrivals"
        self._attr_device_info = _security_device_info()

    @property
    def native_value(self) -> int:
        """Return count of active expected arrivals."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return 0
        security = manager.coordinators.get("security")
        if security is None:
            return 0
        snapshot = security.get_arrivals_snapshot()
        return snapshot.get("expected_count", 0)

    @property
    def extra_state_attributes(self) -> dict:
        """Return arrival and guest details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        security = manager.coordinators.get("security")
        if security is None:
            return {}
        return security.get_arrivals_snapshot()

    @property
    def icon(self) -> str:
        """Dynamic icon based on arrival count."""
        if self.native_value > 0:
            return "mdi:account-arrow-left"
        return "mdi:account-check"

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_schedule_update_ha_state()


class SecurityAggregatorSensor(AggregationEntity, SensorEntity):
    """Locks + cameras roll-up aggregator.

    Entity: sensor.ura_security_coordinator_aggregator
    Device: URA: Security Coordinator
    State: armed | disarmed | partial | alert  (StrEnum _SecurityAggStatus)

    v4.6.9 D2: Single sensor that rolls up all configured lock.* and
    camera.* entities into a security overview the PWA dashboard can bind.

    Bug-class guards:
      #22 — state vocabulary is _SecurityAggStatus (StrEnum); never raw str
      #23 — observation mode does NOT gate state computation; only action
             dispatch is gated in the coordinator. Dashboard shows reality.
      #29 — every status branch (armed/disarmed/partial/alert) is exercised
             by mandatory tests and by the no-entities branch.
      #11 — last_state_change_iso is UTC ISO 8601 str (never datetime obj).
      #37 — extra_state_attributes is a flat dict of ints + one str|None.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-home"
    # Tier 2-DB Reviewer A C1 fix: string-state sensor (armed|disarmed|partial|alert)
    # — NOT a numeric measurement. Omit state_class entirely (matches pattern at
    # SecurityArmedStateSensor:2976 "_attr_state_class = None  # Enum state").

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_aggregator"
        self._attr_name = "Aggregator"
        self._attr_device_info = _security_device_info()

    def _get_aggregator(self) -> dict | None:
        """Fetch live aggregator state from the security coordinator.

        Returns None when the coordinator is unavailable so callers can
        fall back gracefully without repeating the manager lookup.
        """
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return None
            security = manager.coordinators.get("security")
            if security is None:
                return None
            return security.get_security_aggregator_state()
        except Exception:
            _LOGGER.debug(
                "SecurityAggregatorSensor: get_security_aggregator_state() failed",
                exc_info=True,
            )
            return None

    @property
    def native_value(self) -> str:
        """Return overall security status — armed | disarmed | partial | alert."""
        agg = self._get_aggregator()
        if agg is None:
            return "disarmed"
        return agg["status"]

    @property
    def extra_state_attributes(self) -> dict:
        """Return flat lock/camera counts + last_state_change_iso.

        Shape is always stable (Bug Class #37): all 9 keys are always
        present regardless of whether locks/cameras are configured.
        """
        agg = self._get_aggregator()
        if agg is None:
            return {
                "locks_total": 0,
                "locks_locked": 0,
                "locks_unlocked": 0,
                "locks_jammed": 0,
                "cameras_total": 0,
                "cameras_streaming": 0,
                "cameras_idle": 0,
                "cameras_offline": 0,
                "last_state_change_iso": None,
            }
        return {
            "locks_total": agg["locks_total"],
            "locks_locked": agg["locks_locked"],
            "locks_unlocked": agg["locks_unlocked"],
            "locks_jammed": agg["locks_jammed"],
            "cameras_total": agg["cameras_total"],
            "cameras_streaming": agg["cameras_streaming"],
            "cameras_idle": agg["cameras_idle"],
            "cameras_offline": agg["cameras_offline"],
            "last_state_change_iso": agg["last_state_change_iso"],
        }

    @property
    def icon(self) -> str:
        """Dynamic icon based on aggregator status."""
        val = self.native_value
        if val == "alert":
            return "mdi:shield-alert"
        if val == "armed":
            return "mdi:shield-lock"
        if val == "partial":
            return "mdi:shield-half-full"
        return "mdi:shield-off-outline"

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_schedule_update_ha_state()


class EnergyRecentDecisionsSensor(AggregationEntity, SensorEntity):
    """Energy Coordinator decision stream timeline.

    Entity: sensor.ura_energy_coordinator_recent_decisions
    Device: URA: Energy Coordinator
    State: int — number of decisions in the last 24h (never '—'/None/unknown)

    v4.6.9 D3: Exposes the in-memory decision ring buffer from EnergyCoordinator
    as a PWA-consumable sensor. State is always int (0 when buffer empty).

    Bug-class guards:
      #11  — all timestamps are UTC ISO 8601 strings (dt_util.utcnow().isoformat())
      #22  — tou_period values come from TOURateEngine._VALID_PERIODS vocabulary
             (peak | mid_peak | off_peak); never redefined here
      #25  — buffer is deque(maxlen=20); hard cap enforced in coordinator
      #29  — empty-buffer branch returns 0 + empty list (not null/unknown)
      #37  — extra_state_attributes has stable shape: decisions + last_action_at_iso
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:format-list-bulleted-type"
    # Tier 2-DB Reviewer C M1: state is a sliding-window count from a volatile
    # in-memory ring buffer (resets on HA restart). HA long-term statistics
    # would record a discontinuous time series for it. state_class=None opts
    # out of LTS recording; matches the pattern at SecurityAggregatorSensor.

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_recent_decisions"
        self._attr_name = "Recent Decisions"
        self._attr_device_info = _energy_device_info()

    def _get_decisions_data(self) -> dict | None:
        """Fetch decision stream data from EnergyCoordinator.

        Returns None when the coordinator is unavailable; callers fall back
        gracefully to the empty-buffer shape.
        """
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return None
            energy = manager.coordinators.get("energy")
            if energy is None:
                return None
            return energy.get_recent_decisions()
        except Exception:
            _LOGGER.debug(
                "EnergyRecentDecisionsSensor: get_recent_decisions() failed",
                exc_info=True,
            )
            return None

    @property
    def native_value(self) -> int:
        """Return number of decisions in the last 24h.

        Bug Class #29: always returns int 0 on empty buffer — never None/unknown.
        """
        data = self._get_decisions_data()
        if data is None:
            return 0
        return int(data.get("count_24h", 0))

    @property
    def extra_state_attributes(self) -> dict:
        """Return flat decisions list + last_action_at_iso.

        Bug Class #37: both keys are always present regardless of buffer state.
        Bug Class #25: list is capped at 20 entries (enforced by deque in coordinator).
        """
        data = self._get_decisions_data()
        if data is None:
            return {
                "decisions": [],
                "last_action_at_iso": None,
            }
        return {
            "decisions": data.get("decisions", []),
            "last_action_at_iso": data.get("last_action_at_iso"),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to energy entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_ENERGY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ENERGY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle energy entity update signal."""
        self.async_schedule_update_ha_state()


# ============================================================================
# v3.6.21: Music Following Health Sensor
# v3.6.27: Music Following diagnostic sensors (anomaly, transfers, rooms, last)
# ============================================================================


def _music_following_device_info():
    """Return DeviceInfo for the Music Following Coordinator device."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, "music_following_coordinator")},
        name="URA: Music Following Coordinator",
        manufacturer="Universal Room Automation",
        model="Music Following Coordinator",
        sw_version=VERSION,
        via_device=(DOMAIN, "coordinator_manager"),
    )


class MusicFollowingHealthSensor(AggregationEntity, SensorEntity):
    """House-level diagnostic sensor for music following.

    Entity: sensor.ura_music_following_health
    Device: Coordinator device when Music Following Coordinator is active,
            otherwise falls back to integration device.
    State: idle / following / transferring / cooldown / error
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:music-note"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_music_following_health"
        self._attr_name = "Music Following Health"
        self._music_following = None
        # v3.6.27: Use shared device info helper
        self._attr_device_info = _music_following_device_info()

    async def async_added_to_hass(self) -> None:
        """Register diagnostic listener when added to HA."""
        await super().async_added_to_hass()
        mf = self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf:
            self._music_following = mf
            mf.add_diagnostic_listener(self._on_diagnostic_update)

    @callback
    def _on_diagnostic_update(self) -> None:
        """Handle push update from MusicFollowing."""
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> str:
        """Return the primary state."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None:
            return "idle"
        return mf._state

    @property
    def icon(self) -> str:
        val = self.native_value
        return {
            "idle": "mdi:music-note",
            "following": "mdi:music-note-plus",
            "transferring": "mdi:swap-horizontal",
            "cooldown": "mdi:timer-sand",
            "error": "mdi:alert-circle",
        }.get(val, "mdi:music-note")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None:
            return {}
        return mf.get_diagnostic_data()


class ReconcileHealthSensor(AggregationEntity, SensorEntity):
    """House-wide reconcile roll-up. Prior art: MusicFollowingHealthSensor.

    Entity: sensor.ura_reconcile_health (house_reconcile_health)
    State:  total reconciles today across all rooms (int).
    Attrs:  total_reconciles_today, rooms_with_quarantined_actuators,
            top_flappers [{entity_id, room, transition_count}],
            rooms_with_auto_recovery_off [room].
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:backup-restore"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_reconcile_health"
        self._attr_name = "Reconcile Health"

    def _reconcilers(self):
        out = []
        for coord in _get_room_coordinators(self.hass):
            r = getattr(coord, "_actuator_reconciler", None)
            if r is not None:
                out.append((coord, r))
        return out

    @property
    def native_value(self) -> int:
        total = 0
        for _coord, r in self._reconcilers():
            try:
                total += r.reconciles_today
            except Exception:  # noqa: BLE001
                pass
        return total

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        total = 0
        rooms_quarantined = 0
        top_flappers: list[dict] = []
        rooms_ar_off: list[str] = []
        for coord, r in self._reconcilers():
            room_name = coord.entry.data.get("room_name", "Unknown")
            try:
                total += r.reconciles_today
                flapping = r.flapping_entities()
                if flapping:
                    rooms_quarantined += 1
                for f in flapping:
                    top_flappers.append({
                        "entity_id": f["entity_id"],
                        "room": room_name,
                        "transition_count": f.get("transition_count_at_entry"),
                    })
                if not r._auto_recovery_on():
                    rooms_ar_off.append(room_name)
            except Exception:  # noqa: BLE001
                continue
        top_flappers.sort(
            key=lambda x: (x.get("transition_count") or 0), reverse=True,
        )
        return {
            "total_reconciles_today": total,
            "rooms_with_quarantined_actuators": rooms_quarantined,
            "top_flappers": top_flappers[:10],
            "rooms_with_auto_recovery_off": rooms_ar_off,
        }


class MusicFollowingAnomalySensor(AggregationEntity, SensorEntity):
    """Music Following anomaly status.

    v3.6.27: Anomaly detector was wired in v3.6.26 but had no visible sensor.
    Entity: sensor.ura_music_following_anomaly
    Device: URA: Music Following Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_music_following_anomaly"
        self._attr_name = "Music Following Anomaly"
        self._attr_device_info = _music_following_device_info()

    @property
    def native_value(self) -> str:
        """Return the anomaly status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        mf_coord = manager.coordinators.get("music_following")
        if mf_coord is None:
            return "disabled"
        if mf_coord.anomaly_detector is None:
            return "not_configured"
        learning = mf_coord.anomaly_detector.get_learning_status()
        if hasattr(learning, 'value') and learning.value in ("insufficient_data", "learning"):
            return learning.value
        return mf_coord.anomaly_detector.get_worst_severity().value

    @property
    def extra_state_attributes(self) -> dict:
        """v4.5.14: surface AnomalyDetector status summary.

        v4.5.20: SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE now exists and
        is dispatched from MusicFollowingCoordinator._on_transfer_outcome.
        Note that MF is event-driven (no periodic tick) — refresh only
        fires when a transfer outcome happens, which is the right cadence
        for an MF anomaly sensor (its state can't change between transfers).
        """
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        mf_coord = manager.coordinators.get("music_following")
        if mf_coord is None or mf_coord.anomaly_detector is None:
            return {}
        return mf_coord.anomaly_detector.get_status_summary()

    async def async_added_to_hass(self) -> None:
        """v4.5.20: subscribe to MF coord's transfer-outcome refresh signal."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import (
            SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE,
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE,
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_schedule_update_ha_state()


class MusicFollowingTransfersTodaySensor(AggregationEntity, SensorEntity):
    """Total music transfers today with outcome breakdown.

    v3.6.27: Glanceable transfer count with success/failure detail.
    Entity: sensor.ura_music_following_transfers_today
    Device: URA: Music Following Coordinator
    """

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_music_following_transfers_today"
        self._attr_name = "Music Following Transfers Today"
        self._attr_device_info = _music_following_device_info()
        self._music_following = None

    async def async_added_to_hass(self) -> None:
        """Register diagnostic listener when added to HA."""
        await super().async_added_to_hass()
        mf = self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf:
            self._music_following = mf
            mf.add_diagnostic_listener(self._on_diagnostic_update)

    @callback
    def _on_diagnostic_update(self) -> None:
        """Handle push update from MusicFollowing."""
        self.async_schedule_update_ha_state()

    # Stats that indicate actual music-involved transfer attempts
    _TRANSFER_STATS = ("success", "failed", "unverified", "active_playback_blocked")

    @property
    def native_value(self) -> int:
        """Return count of actual transfer attempts today (music-involved only)."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None:
            return 0
        return sum(mf._transfer_stats.get(k, 0) for k in self._TRANSFER_STATS)

    @property
    def icon(self) -> str:
        """Dynamic icon based on failure presence."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is not None and mf._transfer_stats.get("failed", 0) > 0:
            return "mdi:swap-horizontal-circle"
        return "mdi:swap-horizontal-bold"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return outcome breakdown."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None:
            return {}
        stats = mf._transfer_stats
        total = sum(stats.values())
        successes = stats.get("success", 0)
        return {
            "success": successes,
            "failed": stats.get("failed", 0),
            "unverified": stats.get("unverified", 0),
            "cooldown_blocked": stats.get("cooldown_blocked", 0),
            "active_playback_blocked": stats.get("active_playback_blocked", 0),
            "low_confidence": stats.get("low_confidence", 0),
            "ping_pong_suppressed": stats.get("ping_pong_suppressed", 0),
            "success_rate": round(successes / total * 100, 1) if total > 0 else 0.0,
        }


class MusicFollowingActiveRoomsSensor(AggregationEntity, SensorEntity):
    """Rooms with media players configured for music following.

    v3.6.27: Shows which rooms have music following capability.
    Entity: sensor.ura_music_following_active_rooms
    Device: URA: Music Following Coordinator
    """

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_music_following_active_rooms"
        self._attr_name = "Music Following Active Rooms"
        self._attr_device_info = _music_following_device_info()
        self._music_following = None

    async def async_added_to_hass(self) -> None:
        """Register diagnostic listener when added to HA."""
        await super().async_added_to_hass()
        mf = self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf:
            self._music_following = mf
            mf.add_diagnostic_listener(self._on_diagnostic_update)

    @callback
    def _on_diagnostic_update(self) -> None:
        """Handle push update from MusicFollowing."""
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> str:
        """Return CSV of room names with media players, or 'none'."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None:
            return "none"
        rooms = self._get_configured_rooms(mf)
        if not rooms:
            return "none"
        return ", ".join(sorted(rooms))

    @property
    def icon(self) -> str:
        """Dynamic icon."""
        if self.native_value == "none":
            return "mdi:music-off"
        return "mdi:speaker-multiple"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return room and person details."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None:
            return {"rooms": [], "room_count": 0, "enabled_persons": [], "person_count": 0}
        rooms = sorted(self._get_configured_rooms(mf))
        persons = sorted(mf._enabled_persons)
        return {
            "rooms": rooms,
            "room_count": len(rooms),
            "enabled_persons": persons,
            "person_count": len(persons),
        }

    @staticmethod
    def _get_configured_rooms(mf) -> list[str]:
        """Get room names that have room_media_player configured."""
        rooms = []
        try:
            room_entries = mf._get_room_entries()
            for entry_data in room_entries.values():
                if entry_data.get("room_media_player"):
                    room_name = entry_data.get("name", entry_data.get("room_name", "unknown"))
                    rooms.append(room_name)
        except Exception:
            pass
        return rooms


class MusicFollowingLastTransferSensor(AggregationEntity, SensorEntity):
    """Last music transfer result with event details.

    v3.6.27: Shows the most recent transfer outcome.
    Entity: sensor.ura_music_following_last_transfer
    Device: URA: Music Following Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:swap-horizontal"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_music_following_last_transfer"
        self._attr_name = "Music Following Last Transfer"
        self._attr_device_info = _music_following_device_info()
        self._music_following = None

    async def async_added_to_hass(self) -> None:
        """Register diagnostic listener when added to HA."""
        await super().async_added_to_hass()
        mf = self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf:
            self._music_following = mf
            mf.add_diagnostic_listener(self._on_diagnostic_update)

    @callback
    def _on_diagnostic_update(self) -> None:
        """Handle push update from MusicFollowing."""
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> str:
        """Return last transfer result or 'none'."""
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None or not mf._last_transfer_result:
            return "none"
        return mf._last_transfer_result

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return last transfer event details.

        v5.10.0 D1+D8: extended with last_skip_reason / last_skip_* attrs
        so operators can see WHY a transfer didn't fire without new sensors.
        """
        mf = self._music_following or self.hass.data.get(DOMAIN, {}).get("music_following")
        if mf is None or not mf._last_transfer_result:
            return {}
        return {
            "person": mf._last_transfer_person,
            "from_room": mf._last_transfer_from,
            "to_room": mf._last_transfer_to,
            "time": mf._last_transfer_time_iso,
            "result": mf._last_transfer_result,
            # v5.10.0 D1+D8
            "last_skip_reason": getattr(mf, "_last_skip_reason", ""),
            "last_skip_from_room": getattr(mf, "_last_skip_from_room", ""),
            "last_skip_to_room": getattr(mf, "_last_skip_to_room", ""),
            "last_skip_time": getattr(mf, "_last_skip_time_iso", ""),
        }


# ============================================================================
# v3.6.29: Notification Manager Sensors
# ============================================================================


def _nm_device_info():
    """Return DeviceInfo for the Notification Manager device."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, "notification_manager")},
        name="URA: Notification Manager",
        manufacturer="Universal Room Automation",
        model="Notification Manager",
        sw_version=VERSION,
        via_device=(DOMAIN, "coordinator_manager"),
    )


class NMLastNotificationSensor(AggregationEntity, SensorEntity):
    """Last notification severity and details.

    Entity: sensor.ura_notification_last
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_last"
        self._attr_name = "Last Notification"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> str:
        """Return severity of last notification or 'none'."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None or nm.last_notification is None:
            return "none"
        return nm.last_notification.get("severity", "none")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return last notification details."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None or nm.last_notification is None:
            return {}
        data = nm.last_notification
        return {
            "message": data.get("message", ""),
            "coordinator": data.get("coordinator", ""),
            "channels": data.get("channels", []),
            "hazard_type": data.get("hazard_type"),
            "location": data.get("location"),
            "timestamp": data.get("timestamp", ""),
        }


class NMNotificationsTodaySensor(AggregationEntity, SensorEntity):
    """Count of notifications sent today.

    Entity: sensor.ura_notifications_today
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notifications_today"
        self._attr_name = "Notifications Today"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> int:
        """Return count of notifications today."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return 0
        return nm.notifications_today


class NMCooldownRemainingSensor(AggregationEntity, SensorEntity):
    """Seconds remaining in post-ack cooldown.

    Entity: sensor.ura_notification_cooldown_remaining
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-sand"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_cooldown_remaining"
        self._attr_name = "Notification Cooldown Remaining"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> int:
        """Return seconds remaining in cooldown."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return 0
        return nm.cooldown_remaining

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return cooldown context."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {}
        return {
            "hazard_type": nm._cooldown_hazard_type,
            "location": nm._cooldown_location,
            "alert_state": nm.alert_state,
        }


class NMChannelStatusSensor(AggregationEntity, SensorEntity):
    """Per-channel health status.

    Entity: sensor.ura_notification_channel_status
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:check-network"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_channel_status"
        self._attr_name = "Notification Channel Status"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> str:
        """Return overall channel status."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return "not_initialized"
        statuses = nm.channel_status
        if any(ch.get("status") == "degraded" for ch in statuses.values()):
            return "degraded"
        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return per-channel health."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {}
        return nm.channel_status


class NMTriggerSensor(AggregationEntity, SensorEntity):
    """Trigger sensor — state changes on each notification for user HA automations.

    Entity: sensor.ura_notification_trigger
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_trigger"
        self._attr_name = "Notification Trigger"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> str:
        """Return coordinator_severity trigger string."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None or nm.last_notification is None:
            return "none"
        data = nm.last_notification
        coord = data.get("coordinator", "unknown")
        sev = data.get("severity", "unknown").lower()
        return f"{coord}_{sev}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return notification details for automation use."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None or nm.last_notification is None:
            return {}
        data = nm.last_notification
        return {
            "coordinator": data.get("coordinator", ""),
            "severity": data.get("severity", ""),
            "title": data.get("title", ""),
            "message": data.get("message", ""),
            "hazard_type": data.get("hazard_type"),
            "location": data.get("location"),
            "timestamp": data.get("timestamp", ""),
        }


class NMAnomalySensor(AggregationEntity, SensorEntity):
    """Notification volume anomaly status.

    Entity: sensor.ura_notification_anomaly
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_anomaly"
        self._attr_name = "Notification Anomaly"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> str:
        """Return anomaly status."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return "not_initialized"
        if not nm.enabled:
            return "disabled"
        return nm.anomaly_status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return anomaly detail attributes."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {}
        return {
            "dedup_suppressions": nm._dedup_suppressions,
            "quiet_suppressions": nm._quiet_suppressions,
            "notifications_today": nm.notifications_today,
        }


class NMDeliveryRateSensor(AggregationEntity, SensorEntity):
    """Notification delivery success rate.

    Entity: sensor.ura_notification_delivery_rate
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:check-network-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_delivery_rate"
        self._attr_name = "Notification Delivery Rate"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> float:
        """Return delivery success rate."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return 100.0
        return nm.delivery_rate

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return delivery detail."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {}
        return {
            "send_attempts": nm._send_attempts,
            "send_successes": nm._send_successes,
            "send_failures": nm._send_failures,
        }


class NMDiagnosticsSensor(AggregationEntity, SensorEntity, RestoreEntity):
    """Composite NM health and diagnostics.

    Entity: sensor.ura_notification_diagnostics
    Device: URA: Notification Manager

    v3.21.0 D4: RestoreEntity persists NM alert/cooldown/dedup state across restarts.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:stethoscope"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    # NM Cycle C-2 fix-up (M-B1): keep the churny audit ring out of the
    # recorder — the ring updates on every routing decision and would
    # otherwise create per-decision recorder rows for zero analytical
    # value (raw DB rows live in `notification_log`). Mirrors the
    # v5.23.0 pattern for other volatile attribute-carriers.
    _unrecorded_attributes = frozenset({"nm_routing_audit_recent"})

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_diagnostics"
        self._attr_name = "Notification Diagnostics"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener and restore NM state from attributes."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

        # v3.21.0 D4: Restore NM alert state from persisted attributes
        # Review fix R2-F8: Only restore if NM is still in IDLE state.
        # NM's async_setup() may have already recovered from DB — don't overwrite.
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.attributes:
            attrs = last_state.attributes
            persist_data = attrs.get("nm_persistence_state")
            if isinstance(persist_data, dict):
                nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
                if nm is not None and nm._alert_state.value == "idle":
                    nm.restore_persistence_state(persist_data)
                    _LOGGER.debug(
                        "Restored NM persistence state: alert=%s cooldown=%s",
                        persist_data.get("alert_state"),
                        persist_data.get("cooldown_remaining"),
                    )
                elif nm is not None:
                    _LOGGER.debug(
                        "Skipping NM RestoreEntity — already in state %s from DB recovery",
                        nm._alert_state.value,
                    )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> str:
        """Return overall NM health status."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return "not_initialized"
        if not nm.enabled:
            return "disabled"
        # Degraded if any channel is degraded or delivery rate < 80%
        any_degraded = any(
            ch["status"] == "degraded" for ch in nm.channel_status.values()
        )
        if any_degraded or nm.delivery_rate < 80:
            return "degraded"
        return "healthy"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full diagnostic breakdown including persistence state."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {}
        attrs = nm.diagnostics_summary
        # v3.21.0 D4: Include persistence state for RestoreEntity
        attrs["nm_persistence_state"] = nm.get_persistence_state()
        return attrs


class NMInboundTodaySensor(AggregationEntity, SensorEntity):
    """Count of inbound messages received today.

    Entity: sensor.ura_notification_inbound_today
    Device: URA: Notification Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:message-reply-text"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_notification_inbound_today"
        self._attr_name = "Notification Inbound Today"
        self._attr_device_info = _nm_device_info()

    async def async_added_to_hass(self) -> None:
        """Register signal listener."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM entities update signal."""
        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> int:
        """Return count of inbound messages today."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return 0
        return nm.inbound_today

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return inbound breakdown."""
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {}
        return {
            "by_channel": nm.inbound_by_channel,
            "by_command": nm.inbound_by_command,
            "safe_word_configured": nm.safe_word_configured,
            "echo_suppressed": nm.echo_suppressed_count,
        }


# ============================================================================
# v3.7.0-E1: ENERGY COORDINATOR SENSORS
# ============================================================================


def _energy_device_info():
    """Return device info for Energy Coordinator sensors."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, "energy_coordinator")},
        name="URA: Energy Coordinator",
        manufacturer="Universal Room Automation",
        model="Energy Coordinator",
        sw_version=VERSION,
        via_device=(DOMAIN, "coordinator_manager"),
    )


class EnergyTOUPeriodSensor(AggregationEntity, SensorEntity):
    """Current TOU period: off_peak, mid_peak, or peak.

    Entity: sensor.ura_tou_period
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-time-four"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_tou_period"
        self._attr_name = "TOU Period"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return current TOU period."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        return energy.tou_period

    @property
    def extra_state_attributes(self) -> dict:
        """Return TOU details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        info = energy.tou_engine.get_period_info()
        next_t = info.get("next_transition", {})
        return {
            "season": info.get("season"),
            "import_rate": info.get("import_rate"),
            "export_rate": info.get("export_rate"),
            "effective_import_rate": info.get("effective_import_rate"),
            "next_period": next_t.get("next_period"),
            "hours_until_transition": next_t.get("hours_until"),
            "rate_source": info.get("rate_source"),
        }


class EnergyTOURateSensor(AggregationEntity, SensorEntity):
    """Current TOU import rate in $/kWh.

    Entity: sensor.ura_tou_rate
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:currency-usd"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_suggested_display_precision = 4

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_tou_rate"
        self._attr_name = "TOU Rate"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        """Return current import rate."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return round(energy.tou_rate, 6)


class EnergyTOUSeasonSensor(AggregationEntity, SensorEntity):
    """Current TOU season: summer, shoulder, or winter.

    Entity: sensor.ura_tou_season
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:weather-sunny"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_tou_season"
        self._attr_name = "TOU Season"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return current season."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        return energy.tou_season


class EnergyBatteryStrategySensor(AggregationEntity, SensorEntity):
    """Current battery strategy mode and reason.

    Entity: sensor.ura_battery_strategy
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:battery-charging"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_battery_strategy"
        self._attr_name = "Battery Strategy"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return current battery mode."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        status = energy.battery_status
        return status.get("mode", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        """Return battery strategy details.

        v4.5.0 D6: surfaces the new phase-machine attributes (arbitrage_phase,
        peak_buffer_target, target_day_class, next_high_rate_transition,
        charge_window_opens_at, forecast_outlook, arbitrage_chunk_completed,
        arbitrage_charge_lead_time_min) — all of which come through from
        BatteryStrategy.get_status(). Adds D4 cross-ref `evse_paused_by_arbitrage`.

        v4.7.x D4: adds energy-situation visibility attributes:
        - optimization_summary: plain-English one-sentence explanation
        - current_grid_cost_per_hour: live $/hr from current import
        - next_decision_boundary: next TOU transition + expected action
        - current_holds_active: list of active holds preventing normal drain
        - evse_force_charge_until_iso: admin override expiry or None
        All computed from already-loaded state; no DB queries (Reviewer B).
        """
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        attrs = dict(energy.battery_status)
        # v4.3.0 D4 cross-ref: surface today's savings here so users see
        # arbitrage status AND $ saved in one place.
        arb = energy.arbitrage_status or {}
        today = arb.get("today") or {}
        attrs["arbitrage_savings_today"] = round(float(today.get("savings", 0.0)), 2)
        # v4.5.0 D4 cross-ref: which EVSEs are currently paused by arbitrage.
        ev_status = energy.ev_status or {}
        attrs["evse_paused_by_arbitrage"] = list(
            ev_status.get("paused_by_arbitrage", [])
        )

        # ── v4.7.x D4: energy situation visibility ────────────────────────
        try:
            attrs.update(self._build_situation_attrs(energy, ev_status))
        except Exception:
            # Never let D4 enrichment break the sensor read
            pass

        return attrs

    def _build_situation_attrs(
        self, energy: object, ev_status: dict
    ) -> dict:
        """Build D4 situation-visibility attribute dict.

        All computation is constant-time over already-loaded coordinator
        state — no I/O, no DB queries (Reviewer B compliance).

        Bug Class #11/#21: UTC-aware datetimes used throughout.
        """
        decision = energy.last_battery_decision or {}

        # ── holds active ─────────────────────────────────────────────────
        holds: list[str] = []
        if decision.get("evse_battery_hold"):
            holds.append("evse_battery_hold")
        paused_by_arb = ev_status.get("paused_by_arbitrage", [])
        if paused_by_arb:
            holds.append("arbitrage_compound_load")
        paused_by_grid = ev_status.get("paused_by_grid_cap", [])
        if paused_by_grid:
            holds.append("grid_import_cap")

        # ── force-charge override expiry ─────────────────────────────────
        force_charge_until_iso: str | None = ev_status.get("force_charge_until_iso")

        # ── grid cost per hour ───────────────────────────────────────────
        current_rate = 0.0
        grid_cost_per_hour: float | None = None
        try:
            current_rate = float(energy.tou_rate)
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            # Unit-correctness: read the uom-normalized net_power_w property
            # (positive=importing, always W across W/kW Envoy firmware — the
            # v4.5.0 sweep), NOT the raw net_power entity. Reading the raw
            # entity and assuming W made $/h 1000x too low on kW-reporting
            # firmware. net_power_w returns None when the entity is missing.
            net_power_w = energy._battery.net_power_w
            if net_power_w is None:
                grid_cost_per_hour = None
            elif net_power_w > 0:
                grid_cost_per_hour = round(
                    (net_power_w / 1000.0) * current_rate, 2
                )
            else:
                grid_cost_per_hour = 0.0
        except Exception:
            grid_cost_per_hour = None

        # ── next decision boundary ──────────────────────────────────────
        next_boundary: dict | None = None
        try:
            tou = energy._tou
            transition = tou.get_next_transition()
            next_period = transition.get("next_period", "unknown")
            hours_until = transition.get("hours_until", 0)
            minutes_until = round(hours_until * 60)
            # Expected action on transition
            if next_period == "off_peak":
                # B-LOW-1(a) fix-up: off-peak transition now also drives
                # proactive EV turn-on (WS2 widened semantics) unless a
                # battery-protection guard fires (drain / fill-priority /
                # grid-cap / arbitrage) or admin force-charge is active.
                expected_action = (
                    "battery will drain toward reserve target; "
                    "EVs will turn ON proactively unless a "
                    "battery-protection guard is active."
                )
            elif next_period in ("peak", "mid_peak"):
                expected_action = "EV TOU pause will engage; battery holds"
            else:
                expected_action = "re-evaluate"
            next_boundary = {
                "event": f"{next_period}_starts",
                "in_minutes": minutes_until,
                "expected_action": expected_action,
            }
        except Exception:
            next_boundary = None

        # ── plain-English summary ────────────────────────────────────────
        try:
            mode = decision.get("mode", "unknown")
            soc = decision.get("soc")
            reason = decision.get("reason", "")
            summary_parts: list[str] = []

            if "evse_battery_hold" in holds:
                soc_str = f"{int(soc)}%" if soc is not None else "current level"
                summary_parts.append(
                    f"Holding battery at {soc_str} because EV is charging."
                )
            elif mode in ("drain", "discharge"):
                summary_parts.append("Battery is discharging to cover home load.")
            elif mode == "hold":
                summary_parts.append("Battery is holding charge (no import or export).")
            elif mode in ("charge", "grid_charge"):
                summary_parts.append("Battery is charging from the grid (off-peak arbitrage).")
            elif mode == "charge_solar":
                summary_parts.append("Battery is charging from solar.")
            else:
                summary_parts.append(f"Battery mode: {mode}.")

            if grid_cost_per_hour is not None and grid_cost_per_hour > 0:
                summary_parts.append(
                    f"Grid covers current load at ${grid_cost_per_hour:.2f}/hr "
                    f"(${current_rate:.4f}/kWh)."
                )

            if force_charge_until_iso:
                summary_parts.append("Admin force-charge override is active.")

            optimization_summary = " ".join(summary_parts) if summary_parts else reason
        except Exception:
            optimization_summary = decision.get("reason", "")

        return {
            "optimization_summary": optimization_summary,
            "current_grid_cost_per_hour": grid_cost_per_hour,
            "next_decision_boundary": next_boundary,
            "current_holds_active": holds,
            "evse_force_charge_until_iso": force_charge_until_iso,
        }


class InclementStateSensor(AggregationEntity, SensorEntity):
    """Inclement-weather battery-hold decision, surfaced on its own entity.

    Entity: sensor.ura_inclement_state
    Device: URA: Energy Coordinator

    v5.5.1 D6: the inclement decision already rides as an attribute pack on
    EnergyBatteryStrategySensor (its extra_state_attributes returns the whole
    battery_status dict, which carries every inclement_* key). This sensor
    re-surfaces only the inclement-scoped subset on a dedicated entity so it
    can be dashboarded without the full battery payload. Observability-only —
    it reads already-loaded coordinator state, computes nothing, fires no I/O
    and no DB queries (Reviewer B discipline, mirrored from the sibling).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:weather-lightning"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_inclement_state"
        self._attr_name = "Inclement State"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return the headline inclement tier (none / notice / watch / warn)."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        status = energy.battery_status
        return status.get("inclement_tier", "none")

    @property
    def extra_state_attributes(self) -> dict:
        """Return only the inclement-scoped subset of battery_status.

        Each key is pulled via .get(...) so a missing inclement_* key never
        raises. No whole-dict copy — this entity is inclement-scoped, not a
        battery mirror. Constant-time over already-loaded state; no I/O / no
        DB queries (Reviewer B compliance, mirrored from the sibling).
        """
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        status = energy.battery_status
        return {
            "storm_forecast": status.get("storm_forecast"),
            "inclement_hold_depth": status.get("inclement_hold_depth"),
            "inclement_source": status.get("inclement_source"),
            "active_alert_event": status.get("active_alert_event"),
            "inclement_gated_out_events": status.get("inclement_gated_out_events"),
            "inclement_expires_at": status.get("inclement_expires_at"),
            "inclement_grid_precharge": status.get("inclement_grid_precharge"),
            "inclement_reserve_floor": status.get("inclement_reserve_floor"),
            "inclement_reason": status.get("inclement_reason"),
            "inclement_solar_horizon": status.get("inclement_solar_horizon"),
        }


class EnergyDrainPrecedenceStateSensor(AggregationEntity, SensorEntity):
    """EVSE Drain-Precedence state machine observability (Session B1).

    Entity: sensor.ura_energy_drain_precedence_state
    Device: URA: Energy Coordinator

    State value: the current `DPState` (`hold_only` / `hold_pre_eval` /
    `eval_transition` / `transitioned` / `must_start_forced`). Attributes
    mount `DrainPrecedenceState.to_attrs()` verbatim (state, since,
    hold_started_at, transitioned_at, must_start_by_dt, last_eval_at,
    last_eval_snapshot) so operators + reviewers can watch the machine
    in real time. Session B2 populates last_eval_snapshot on each eval.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:state-machine"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_drain_precedence_state"
        # B2c-2 item 6 rename (operator ratification 2026-07-17, planning
        # doc §373): user-facing name is "EV Charging Plan"; unique_id
        # stays technical (`drain_precedence_state`) so entity history +
        # dashboard references survive the rename.
        self._attr_name = "EV Charging Plan"
        self._attr_device_info = _energy_device_info()

    def _get_carrier(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return getattr(energy, "_dp_carrier", None)

    @property
    def native_value(self) -> str:
        carrier = self._get_carrier()
        if carrier is None:
            return "unknown"
        try:
            return carrier.state.value
        except Exception:  # noqa: BLE001
            return "unknown"

    @property
    def extra_state_attributes(self) -> dict:
        carrier = self._get_carrier()
        if carrier is None:
            return {}
        try:
            return dict(carrier.to_attrs())
        except Exception:  # noqa: BLE001
            return {}


class EnergySolarDayClassSensor(AggregationEntity, SensorEntity):
    """Solar day classification from Solcast forecast.

    Entity: sensor.ura_solar_day_class
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:white-balance-sunny"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_solar_day_class"
        self._attr_name = "Solar Day Class"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return solar day classification."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        return energy.solar_day_class

    @property
    def extra_state_attributes(self) -> dict:
        """Return Solcast forecast details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        battery = energy.battery_strategy
        return {
            "forecast_today_kwh": battery.solcast_today,
            "forecast_remaining_kwh": battery.solcast_remaining,
        }


# ============================================================================
# v4.7.x Cycle A: WEATHER PROVIDER MANAGER SENSORS
# ============================================================================


class WeatherActiveProviderSensor(AggregationEntity, SensorEntity):
    """Active weather provider entity ID (or 'none' / 'all_stale').

    Entity: sensor.ura_weather_active_provider
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:weather-partly-cloudy"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_weather_active_provider"
        self._attr_name = "Weather Active Provider"
        self._attr_device_info = _energy_device_info()

    async def async_added_to_hass(self) -> None:
        """Subscribe to SIGNAL_WEATHER_PROVIDER_CHANGED for reactive updates (WPM-H1)."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_WEATHER_PROVIDER_CHANGED
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_WEATHER_PROVIDER_CHANGED, self._on_weather_signal,
            )
        )

    @callback
    def _on_weather_signal(self, _payload=None) -> None:
        """Handle provider-changed or divergence signal."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return False when WeatherProviderManager is not set up (WPM-H5)."""
        return self.hass.data.get(DOMAIN, {}).get("weather_manager") is not None

    @property
    def native_value(self) -> str:
        """Return active provider entity_id, 'none', or 'all_stale'."""
        try:
            mgr = self.hass.data.get(DOMAIN, {}).get("weather_manager")
            if mgr is None:
                return "none"
            return mgr.provider_status_str
        except Exception:
            return "none"

    @property
    def extra_state_attributes(self) -> dict:
        """Return provider list health details."""
        try:
            mgr = self.hass.data.get(DOMAIN, {}).get("weather_manager")
            if mgr is None:
                return {}
            active = mgr.active_provider
            rank = mgr.priority_rank_for(active) if active is not None else None
            return {
                "priority_rank": rank,
                "healthy_count": mgr.healthy_provider_count,
                "total_count": mgr.total_provider_count,
                "failover_reason": mgr.failover_reason,
                "apparent_confidence": mgr.apparent_confidence,
                "provider_health": mgr.provider_health_map,
            }
        except Exception:
            return {}


class WeatherApparentForecastHighSensor(AggregationEntity, SensorEntity):
    """Today's apparent forecast high temperature from the active provider.

    Entity: sensor.ura_weather_apparent_forecast_high
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermometer-chevron-up"
    _attr_native_unit_of_measurement = "°F"
    _attr_state_class = "measurement"
    _attr_suggested_display_precision = 1
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_weather_apparent_forecast_high"
        self._attr_name = "Weather Apparent Forecast High"
        self._attr_device_info = _energy_device_info()

    async def async_added_to_hass(self) -> None:
        """Subscribe to provider-changed signal for reactive updates (WPM-H1)."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_WEATHER_PROVIDER_CHANGED
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_WEATHER_PROVIDER_CHANGED, self._on_weather_signal,
            )
        )

    @callback
    def _on_weather_signal(self, _payload=None) -> None:
        """Handle provider-changed signal — push updated value to HA."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return False when WeatherProviderManager is absent or has no forecast (WPM-H5)."""
        try:
            mgr = self.hass.data.get(DOMAIN, {}).get("weather_manager")
            return mgr is not None and mgr._cached_forecast is not None
        except Exception:
            return False

    @property
    def native_value(self) -> float | None:
        """Return today's apparent high directly from WPM (WPM-H2 — no EC indirection)."""
        try:
            mgr = self.hass.data.get(DOMAIN, {}).get("weather_manager")
            if mgr is None:
                return None
            return mgr.current_apparent_forecast_high()
        except Exception:
            return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return forecast detail attributes sourced entirely from WPM (WPM-H2)."""
        try:
            mgr = self.hass.data.get(DOMAIN, {}).get("weather_manager")
            if mgr is None:
                return {}
            forecast = mgr._cached_forecast
            if forecast is None:
                return {}
            return {
                "raw_high": forecast.raw_high,
                "apparent_low": forecast.apparent_low,
                "provider_source": forecast.provider_id,
                "confidence": forecast.apparent_confidence,
                "divergence_f": forecast.divergence_f,
            }
        except Exception:
            return {}


# ============================================================================
# v4.7.1 Cycle B: DYNAMIC PRESET SENSORS
# ============================================================================


def _get_dynamic_preset_source(hass):
    """Return DynamicPresetOverrideSource from EC coordinator (or None)."""
    try:
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return getattr(energy, "_dynamic_preset_source", None)
    except Exception:
        return None


def _get_dynamic_preset_overrides(hass) -> dict:
    """Return the per-zone overrides dict from EC (or {})."""
    try:
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return getattr(energy, "_dynamic_preset_overrides", {}) or {}
    except Exception:
        return {}


def _get_dynamic_preset_skip_reasons(hass) -> dict:
    """v4.7.7 B2: per-zone skip_reason from EC's last DPM eval (or {}).

    Read by `DynamicPresetOverridesAppliedSensor.extra_state_attributes`
    to surface why each zone was skipped this tick.
    """
    try:
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return getattr(energy, "_dynamic_preset_skip_reasons", {}) or {}
    except Exception:
        return {}


def _wpm_available(hass) -> bool:
    """Return True when WeatherProviderManager exists and has a cached forecast."""
    try:
        mgr = hass.data.get(DOMAIN, {}).get("weather_manager")
        return mgr is not None and mgr._cached_forecast is not None
    except Exception:
        return False


class DynamicPresetActiveBucketSensor(AggregationEntity, SensorEntity, RestoreEntity):
    """Active thermal load bucket for a canonical HVAC zone.

    State: cool | mild | hot | extreme | unavailable
    Entity: sensor.ura_dynamic_preset_active_bucket_<zone_id>
    Device: URA: Energy Coordinator

    Restores bucket + last_transition_at on HA restart (Bug #10 compliance).
    Subscribes to SIGNAL_DYNAMIC_PRESET_TRANSITIONED for reactive updates (WPM-H1 pattern).

    v4.7.1 Cycle B: B3.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermometer-auto"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, zone_id: str, zone_name: str
    ) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._attr_unique_id = f"{DOMAIN}_dynamic_preset_active_bucket_{zone_id}"
        self._attr_name = f"Dynamic Preset Bucket {zone_name}"
        # v4.7.7 B3: migrated from Energy to HVAC Coordinator device card.
        # Registry device_id is reassigned via _HVAC_DEVICE_MIGRATIONS in
        # __init__.py for entities created before v4.7.7.
        self._attr_device_info = _hvac_device_info()
        # Cached state for RestoreEntity (Bug #10)
        self._restored_bucket: str | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to transition signal and restore state (WPM-H1 + Bug #10)."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import (
            SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED,
            SIGNAL_DYNAMIC_PRESET_TRANSITIONED,
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DYNAMIC_PRESET_TRANSITIONED, self._on_transition,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED, self._on_updated,
            )
        )
        # Restore cross-restart state (Bug #10)
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable", None):
            self._restored_bucket = last_state.state
            # Inject into DynamicPresetOverrideSource when it's available
            self._try_restore_to_source(last_state)
        # v4.7.18 D5: also restore relax-ceiling counter attrs even when
        # bucket state is unknown/unavailable (counters are independent
        # of bucket — they may be > 0 with bucket="unknown" if the gate
        # fired in a session that crashed before bucket initialization).
        if last_state is not None:
            self._try_restore_blocked_counter(last_state)

    def _try_restore_to_source(self, last_state) -> None:
        """Inject restored state into DynamicPresetOverrideSource (Bug #10)."""
        from datetime import datetime, timezone
        try:
            source = _get_dynamic_preset_source(self.hass)
            if source is None:
                return
            bucket = last_state.state
            # Try to get last_transition_iso from last_state attributes
            last_tx_iso = (last_state.attributes or {}).get("last_transition_iso")
            if last_tx_iso:
                try:
                    last_tx = datetime.fromisoformat(last_tx_iso)
                    if last_tx.tzinfo is None:
                        last_tx = last_tx.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    last_tx = dt_util.utcnow()
            else:
                last_tx = dt_util.utcnow()
            source.restore_zone_state(self._zone_id, bucket, last_tx)
        except Exception:
            pass

    def _try_restore_blocked_counter(self, last_state) -> None:
        """v4.7.18 D5: hydrate the per-zone relax-ceiling counter from
        RestoreEntity attrs on startup. Mirrors `_try_restore_to_source`
        — counter survives across HA restart (Bug #10 compliance for
        the new attrs).
        """
        from datetime import datetime, timezone
        try:
            source = _get_dynamic_preset_source(self.hass)
            if source is None:
                return
            attrs = last_state.attributes or {}
            raw_count = attrs.get("relax_ceiling_blocked_count")
            raw_last = attrs.get("relax_ceiling_last_blocked_at")
            last_blocked = None
            if raw_last:
                try:
                    last_blocked = datetime.fromisoformat(raw_last)
                    if last_blocked.tzinfo is None:
                        last_blocked = last_blocked.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    last_blocked = None
            source.restore_blocked_counter(self._zone_id, raw_count, last_blocked)
        except Exception:  # noqa: BLE001
            pass

    @callback
    def _on_transition(self, payload=None) -> None:
        """Handle bucket transition signal — push updated state to HA."""
        if payload and payload.get("zone_id") == self._zone_id:
            self.async_write_ha_state()

    @callback
    def _on_updated(self, _payload=None) -> None:
        """Handle generic overrides-updated signal."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Unavailable when WPM is missing (WPM-H5 pattern)."""
        return _wpm_available(self.hass)

    @property
    def native_value(self) -> str | None:
        """Return current bucket or None."""
        try:
            source = _get_dynamic_preset_source(self.hass)
            if source is None:
                return self._restored_bucket
            state = source.get_zone_state(self._zone_id)
            return state.get("bucket") or self._restored_bucket
        except Exception:
            return self._restored_bucket

    @property
    def extra_state_attributes(self) -> dict:
        """Return bucket detail attributes."""
        try:
            source = _get_dynamic_preset_source(self.hass)
            overrides = _get_dynamic_preset_overrides(self.hass)
            zone_overrides = overrides.get(self._zone_id, [])

            state = source.get_zone_state(self._zone_id) if source else {}

            # Get WPM data for relative_delta + rolling median context.
            # v4.7.17.2: attribute names renamed to reflect the new semantic
            # (forecast vs 14-day rolling median, not forecast vs cool_target).
            mgr = self.hass.data.get(DOMAIN, {}).get("weather_manager")
            apparent_high = None
            relative_delta_f = None
            rolling_median = None
            if mgr is not None:
                apparent_high = mgr.current_apparent_forecast_high()
                relative_delta_f = mgr.baseline_delta_for_zone(self._zone_id, "home")
                if apparent_high is not None and relative_delta_f is not None:
                    rolling_median = apparent_high - relative_delta_f

            # v4.7.17.2: derive the operator-knob-driven cool_high adjustment
            # so the sensor surfaces what DPM is actually doing today.
            cool_high_adjustment_f = None
            if relative_delta_f is not None and mgr is not None:
                try:
                    from .domain_coordinators.energy_const import (
                        CONF_DPM_COOL_DAY_RELAX_F,
                        CONF_DPM_HOT_DAY_TIGHTEN_F,
                        DEFAULT_DPM_COOL_DAY_RELAX_F,
                        DEFAULT_DPM_HOT_DAY_TIGHTEN_F,
                    )
                    from .domain_coordinators.dynamic_preset import (
                        _compute_cool_high_adjustment,
                    )
                    cm_opts = self._config_entry.options if self._config_entry else {}
                    _relax = float(cm_opts.get(
                        CONF_DPM_COOL_DAY_RELAX_F, DEFAULT_DPM_COOL_DAY_RELAX_F,
                    ))
                    _tighten = float(cm_opts.get(
                        CONF_DPM_HOT_DAY_TIGHTEN_F, DEFAULT_DPM_HOT_DAY_TIGHTEN_F,
                    ))
                    cool_high_adjustment_f = round(
                        _compute_cool_high_adjustment(
                            relative_delta_f, _relax, _tighten,
                        ),
                        2,
                    )
                except Exception:  # noqa: BLE001
                    cool_high_adjustment_f = None

            return {
                # v4.7.17.2: legacy `delta_f` / `baseline_high_f` names
                # renamed for semantic accuracy. Kept the same shape.
                "relative_delta_f": round(relative_delta_f, 1) if relative_delta_f is not None else None,
                "apparent_high_f": apparent_high,
                "rolling_median_apparent_high_f": rolling_median,
                "cool_high_adjustment_f": cool_high_adjustment_f,
                "last_transition_iso": state.get("last_transition_iso"),
                "dwell_remaining_min": state.get("dwell_remaining_min"),
                "active_overrides_count": len(zone_overrides),
                # v4.7.18 D5: heat-wave relax-ceiling gate telemetry.
                # `relax_ceiling_f` is the resolved °F threshold (None when
                # mode=off or DPM has not evaluated for this zone yet).
                # `relax_ceiling_source` is one of: auto / manual_conservative /
                # manual_moderate / manual_aggressive / off / None.
                # `relax_ceiling_blocked_count` is monotonically non-decreasing
                # and persists via RestoreEntity. `relax_ceiling_last_blocked_at`
                # is ISO-8601 timestamp of the most recent gate fire (or None).
                "relax_ceiling_f": state.get("relax_ceiling_f"),
                "relax_ceiling_source": state.get("relax_ceiling_source"),
                "relax_ceiling_blocked_count": state.get("relax_ceiling_blocked_count", 0),
                "relax_ceiling_last_blocked_at": state.get("relax_ceiling_last_blocked_at"),
            }
        except Exception:
            return {}


class DynamicPresetRangeSensor(AggregationEntity, SensorEntity):
    """Effective home preset range for the current bucket.

    State: "cool_low–cool_high" (e.g. "70.0–76.0") or None when unavailable.
    Entity: sensor.ura_dynamic_preset_range_<zone_id>
    Device: URA: Energy Coordinator

    v4.7.1 Cycle B: B3.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermometer-lines"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, zone_id: str, zone_name: str
    ) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._attr_unique_id = f"{DOMAIN}_dynamic_preset_range_{zone_id}"
        self._attr_name = f"Dynamic Preset Range {zone_name}"
        # v4.7.7 B3: migrated from Energy to HVAC Coordinator device card.
        self._attr_device_info = _hvac_device_info()

    async def async_added_to_hass(self) -> None:
        """Subscribe to override-updated signal (WPM-H1 pattern)."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED, self._on_updated,
            )
        )

    @callback
    def _on_updated(self, _payload=None) -> None:
        """Handle overrides-updated signal — push state to HA."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Unavailable when WPM is missing (WPM-H5 pattern)."""
        return _wpm_available(self.hass)

    @property
    def native_value(self) -> str | None:
        """Return 'low–high' string for the active home override, or None."""
        try:
            overrides = _get_dynamic_preset_overrides(self.hass)
            zone_overrides = overrides.get(self._zone_id, [])
            for override in zone_overrides:
                if override.preset == "home" and override.cool_low is not None and override.cool_high is not None:
                    return f"{override.cool_low:.1f}–{override.cool_high:.1f}"
            return None
        except Exception:
            return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return full grid of effective ranges (home + sleep × 4 buckets)."""
        try:
            overrides_dict = _get_dynamic_preset_overrides(self.hass)
            zone_overrides = overrides_dict.get(self._zone_id, [])

            home_overrides = {o.preset: {"low": o.cool_low, "high": o.cool_high, "bucket": o.bucket}
                              for o in zone_overrides if o.preset == "home"}
            sleep_overrides = {o.preset: {"low": o.cool_low, "high": o.cool_high, "bucket": o.bucket}
                               for o in zone_overrides if o.preset == "sleep"}

            return {
                "zone_id": self._zone_id,
                "zone_name": self._zone_name,
                "home_override": home_overrides.get("home"),
                "sleep_override": sleep_overrides.get("sleep"),
                "all_overrides": [
                    {
                        "preset": o.preset,
                        "cool_low": o.cool_low,
                        "cool_high": o.cool_high,
                        "bucket": o.bucket,
                        "source": o.source,
                    }
                    for o in zone_overrides
                ],
            }
        except Exception:
            return {}


class DynamicPresetOverridesAppliedSensor(AggregationEntity, SensorEntity):
    """Count of zones with an active dynamic preset override.

    State: int (count of zones with at least one dynamic_preset override).
    Entity: sensor.ura_dynamic_preset_overrides_applied
    Device: URA: Energy Coordinator

    v4.7.1 Cycle B: B3.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermometer-check"
    # HIGH A4/C-M2: no state_class — this count resets to 0 on restart, so
    # HA Long-Term Statistics would record a discontinuous time series.
    # Matches EnergyRecentDecisionsSensor pattern (same volatile-counter reason).
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_dynamic_preset_overrides_applied"
        self._attr_name = "Dynamic Preset Overrides Applied"
        # v4.7.7 B3: migrated from Energy to HVAC Coordinator device card.
        self._attr_device_info = _hvac_device_info()

    async def async_added_to_hass(self) -> None:
        """Subscribe to override-updated and transition signals.

        v4.7.9 D2: third subscription to SIGNAL_DPM_SKIP_REASONS_UPDATED so
        `skipped_zones_with_reason` refreshes when ONLY skip-reasons change
        between ticks (the overrides dict can stay empty for days while
        reasons transition; without this signal the attr was stale).
        Unsub is tracked via `async_on_remove` (Bug Class #38 safe). The
        callback `_on_signal` is `@callback`-decorated (Bug Class #42 safe).
        """
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import (
            SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED,
            SIGNAL_DYNAMIC_PRESET_TRANSITIONED,
            SIGNAL_DPM_SKIP_REASONS_UPDATED,  # v4.7.9 D2
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED, self._on_signal,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DYNAMIC_PRESET_TRANSITIONED, self._on_signal,
            )
        )
        # v4.7.9 D2: third subscription — see method docstring.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DPM_SKIP_REASONS_UPDATED, self._on_signal,
            )
        )

    @callback
    def _on_signal(self, _payload=None) -> None:
        """Handle signal — push updated count to HA.

        v4.7.9 B-L4 fix-up: signal is payload-less by contract; sensor
        recomputes attrs from latest coordinator state via the
        `extra_state_attributes` property on the next HA state read.
        Idempotent — double-fire (overrides + reasons signals on the
        same tick) writes the same value twice with no side effects.
        """
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True when WPM is set up."""
        return _wpm_available(self.hass)

    @property
    def native_value(self) -> int:
        """Return count of zones with at least one active dynamic preset override."""
        try:
            overrides = _get_dynamic_preset_overrides(self.hass)
            return sum(1 for v in overrides.values() if v)
        except Exception:
            return 0

    @property
    def extra_state_attributes(self) -> dict:
        """Return per-zone breakdown and dwell-remaining."""
        try:
            overrides = _get_dynamic_preset_overrides(self.hass)
            source = _get_dynamic_preset_source(self.hass)
            breakdown = []
            for zone_id, zone_overrides in overrides.items():
                if not zone_overrides:
                    continue
                state = source.get_zone_state(zone_id) if source else {}
                for o in zone_overrides:
                    breakdown.append({
                        "zone": zone_id,
                        "preset": o.preset,
                        "cool_low": o.cool_low,
                        "cool_high": o.cool_high,
                        "bucket": o.bucket,
                    })

            skipped_zones = [
                zone_id for zone_id, v in overrides.items() if not v
            ]
            # v4.7.7 B2: surface the reason per skipped zone. Reasons are
            # captured in energy.py:_async_evaluate_dynamic_presets per
            # tick and stored on the EC instance. List-of-dicts so a
            # frontend card can render a tooltip per zone.
            # Bug Class #45 safe: dict-comprehension keyed by zone_id,
            # no lambda closure over loop variables.
            reasons_by_zone = _get_dynamic_preset_skip_reasons(self.hass)
            skipped_zones_with_reason = [
                {
                    "zone_id": zone_id,
                    "reason": reasons_by_zone.get(zone_id, "unknown"),
                }
                for zone_id in skipped_zones
            ]
            dwell_remaining = {}
            if source:
                for zone_id in overrides:
                    state = source.get_zone_state(zone_id)
                    dr = state.get("dwell_remaining_min")
                    if dr is not None:
                        dwell_remaining[zone_id] = dr

            return {
                "breakdown": breakdown,
                "skipped_zones": skipped_zones,
                "skipped_zones_with_reason": skipped_zones_with_reason,
                "dwell_remaining_per_zone_min": dwell_remaining,
            }
        except Exception:
            return {}


# ============================================================================
# v4.7.1 fix-up D4: HVAC ACTIVE PRESET OVERRIDES DIAGNOSTIC SENSOR
# ============================================================================


class HVACActivePresetOverridesSensor(AggregationEntity, SensorEntity):
    """D4: Diagnostic sensor — count + detail of active preset overrides across all zones.

    State: integer count of active override records across all zones for the
    current preset (reading from EC's _dynamic_preset_overrides and
    OverrideEngine).

    Attributes:
      - by_zone: {zone_id: [{preset, source, cool_low, cool_high, ...}]}
      - house_state: current house_state string
      - master_enabled: bool (HVAC guest_mode_actuation_enabled)
      - resolved_ranges: {zone_id: {"cool_low":float, "cool_high":float,
                                    "sources": {field: source_name}}}

    Entity: sensor.ura_hvac_coordinator_active_preset_overrides
    Device: URA: HVAC Coordinator

    v4.7.1 fix-up D4 (PLANNING_v4.7.x_guest_mode_actuation_phase1.md §5.D4).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermostat-cog"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_active_preset_overrides"
        self._attr_name = "Active Preset Overrides"
        self._attr_device_info = _hvac_device_info()

    def _get_hvac(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("hvac") if manager else None

    def _get_ec(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    async def async_added_to_hass(self) -> None:
        """Subscribe to override-updated and house-state signals."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import (
            SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED,
            SIGNAL_HOUSE_STATE_CHANGED,
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED, self._on_signal,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HOUSE_STATE_CHANGED, self._on_signal,
            )
        )

    @callback
    def _on_signal(self, _payload=None) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._get_hvac() is not None

    @property
    def native_value(self) -> int:
        """Return total count of active override records across all zones."""
        try:
            ec = self._get_ec()
            if ec is None:
                return 0
            hvac = self._get_hvac()
            if hvac is None:
                return 0
            master_enabled = getattr(hvac, "_guest_mode_actuation_enabled", True)
            if not master_enabled:
                return 0

            from .domain_coordinators.preset_overrides import OverrideEngine
            engine = OverrideEngine()
            house_state = getattr(hvac, "_house_state", "")
            target_preset = hvac.preset_manager.get_preset_for_house_state(house_state) or "home"
            all_overrides = getattr(ec, "_dynamic_preset_overrides", {})

            count = 0
            for zone_id, zone_overrides in all_overrides.items():
                active = engine.get_active_overrides(
                    zone_id, target_preset, house_state, master_enabled, zone_overrides
                )
                count += len(active)
            return count
        except Exception:
            return 0

    @property
    def extra_state_attributes(self) -> dict:
        """Return per-zone breakdown, resolved ranges, and master state."""
        try:
            ec = self._get_ec()
            hvac = self._get_hvac()
            if ec is None or hvac is None:
                return {}

            from .domain_coordinators.preset_overrides import OverrideEngine
            engine = OverrideEngine()
            house_state = getattr(hvac, "_house_state", "")
            master_enabled = getattr(hvac, "_guest_mode_actuation_enabled", True)
            target_preset = hvac.preset_manager.get_preset_for_house_state(house_state) or "home"
            all_overrides = getattr(ec, "_dynamic_preset_overrides", {})

            by_zone: dict = {}
            resolved_ranges: dict = {}

            for zone_id, zone_overrides in all_overrides.items():
                active = engine.get_active_overrides(
                    zone_id, target_preset, house_state, master_enabled, zone_overrides
                )
                if not active:
                    continue
                by_zone[zone_id] = [
                    {
                        "preset": o.preset,
                        "source": o.source,
                        "cool_low": o.cool_low,
                        "cool_high": o.cool_high,
                        "priority": o.priority,
                        "bucket": o.bucket,
                    }
                    for o in active
                ]

                # Get baseline from preset manager
                baseline = hvac.preset_manager.get_seasonal_setpoints(target_preset)
                if baseline is not None:
                    baseline_cool, _ = baseline
                    baseline_low = baseline_cool - 7.0
                    baseline_high = baseline_cool
                    resolved = engine.resolve_range(baseline_low, baseline_high, active)
                    resolved_ranges[zone_id] = {
                        "cool_low": resolved.cool_low,
                        "cool_high": resolved.cool_high,
                        "sources": resolved.sources,
                    }

            return {
                "by_zone": by_zone,
                "house_state": house_state,
                "master_enabled": master_enabled,
                "resolved_ranges": resolved_ranges,
            }
        except Exception:
            return {}


# ============================================================================
# v3.7.0-E2: ENERGY POOL + EV SENSORS
# ============================================================================


class EnergyPoolOptimizationSensor(AggregationEntity, SensorEntity):
    """Current pool optimization state.

    Entity: sensor.ura_pool_optimization
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:pool"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_pool_optimization"
        self._attr_name = "Pool Optimization"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return pool optimization state."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        return energy.pool_status.get("state", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        """Return pool details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return energy.pool_status


class EnergyEVChargingStatusSensor(AggregationEntity, SensorEntity):
    """EV charging status across all EVSEs.

    Entity: sensor.ura_ev_charging_status
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:ev-station"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_ev_charging_status"
        self._attr_name = "EV Charging Status"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return overall EV status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        status = energy.ev_status
        paused = status.get("paused_by_energy", [])
        if paused:
            return "paused"
        # Check if any EVSE is actively charging
        for key, val in status.items():
            if isinstance(val, dict) and val.get("charging"):
                return "charging"
        return "idle"

    @property
    def extra_state_attributes(self) -> dict:
        """Return per-EVSE details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return energy.ev_status


# ============================================================================
# v3.7.0-E3: CIRCUIT + GENERATOR SENSORS
# ============================================================================


class EnergyCircuitAnomalySensor(AggregationEntity, SensorEntity):
    """Circuit anomaly state.

    Entity: sensor.ura_circuit_anomaly
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:flash-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_circuit_anomaly"
        self._attr_name = "Circuit Anomaly"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return anomaly state."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        status = energy.circuit_status
        count = status.get("anomaly_count", 0)
        if count > 0:
            return f"alert ({count})"
        return "normal"

    @property
    def extra_state_attributes(self) -> dict:
        """Return circuit monitoring details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return energy.circuit_status


class EnergyGeneratorStatusSensor(AggregationEntity, SensorEntity):
    """Generator status sensor.

    Entity: sensor.ura_generator_status
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:engine"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_generator_status"
        self._attr_name = "Generator Status"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        """Return generator status."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        return energy.generator_status.get("status", "unknown")


# ============================================================================
# v3.7.0-E4: BILLING + COST SENSORS
# ============================================================================


class EnergyCoordCostTodaySensor(AggregationEntity, SensorEntity):
    """Net energy cost today (coordinator-level).

    Entity: sensor.ura_energy_cost_today
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:cash"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_cost_today"
        self._attr_name = "Energy Cost Today"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.cost_today

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        status = energy.billing_status
        return {
            "import_kwh": status.get("import_kwh_today"),
            "import_cost": status.get("import_cost_today"),
            "export_kwh": status.get("export_kwh_today"),
            "export_credit": status.get("export_credit_today"),
        }


class EnergyCostCycleSensor(AggregationEntity, SensorEntity):
    """Cost so far in billing cycle.

    Entity: sensor.ura_energy_cost_this_cycle
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_cost_this_cycle"
        self._attr_name = "Energy Cost This Cycle"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.cost_this_cycle

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        status = energy.billing_status
        return {
            "days_in_cycle": status.get("days_in_cycle"),
            "cycle_start_date": status.get("cycle_start_date"),
            "import_kwh_cycle": status.get("import_kwh_cycle"),
            "export_kwh_cycle": status.get("export_kwh_cycle"),
        }


class EnergyPredictedBillSensor(AggregationEntity, SensorEntity):
    """Predicted monthly bill (available after 7 days in cycle).

    Entity: sensor.ura_energy_predicted_bill
    Device: URA: Energy Coordinator

    v4.6.10 D6: removed state_class MEASUREMENT — MONETARY + MEASUREMENT is rejected by
    HA recorder (HA core issues #86780, #88457, #115692).  Predicted bill is an
    instantaneous estimate, so no state_class is the correct pattern.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:receipt-text"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_predicted_bill"
        self._attr_name = "Predicted Bill"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.predicted_bill

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        billing = energy.billing_status
        attrs = {}
        label = billing.get("prediction_label") if billing else None
        if label:
            attrs["status"] = label
        if billing:
            attrs["days_in_cycle"] = billing.get("days_in_cycle", 0)
            attrs["cycle_start_date"] = billing.get("cycle_start_date", "")
        # v4.2.17: Utility meter divergence
        divergence = energy.utility_meter_divergence
        if divergence:
            attrs["prediction_source"] = divergence.get("prediction_source", "envoy")
            attrs["utility_kwh"] = divergence.get("utility_kwh")
            attrs["envoy_kwh"] = divergence.get("envoy_kwh")
            attrs["utility_divergence_pct"] = divergence.get("divergence_pct")

        # v4.3.0 D4: arbitrage counterfactual
        # Show what the bill WOULD be without arbitrage, plus accrued and
        # projected savings, so the user can see if arbitrage is paying off.
        arb = energy.arbitrage_status or {}
        cycle_savings = float((arb.get("cycle") or {}).get("savings", 0.0))
        pace = arb.get("pace") or {}
        avg_per_day = float(pace.get("avg_savings_per_day", 0.0))
        days_in_cycle = int(billing.get("days_in_cycle", 0)) if billing else 0

        # v4.3.0 Review L19 fix: derive actual cycle length from cycle_start_date
        # plus one calendar month, instead of hardcoded 30. PEC bill cycles
        # follow calendar months and are 28-31 days depending on the month.
        cycle_length_days = 30  # safety fallback
        cycle_start_str = billing.get("cycle_start_date") if billing else None
        if cycle_start_str:
            try:
                from dateutil.relativedelta import relativedelta
                cycle_start_dt = dt_util.parse_datetime(cycle_start_str)
                if cycle_start_dt is None:
                    from datetime import datetime as _dt
                    cycle_start_dt = _dt.fromisoformat(cycle_start_str)
                next_cycle_dt = cycle_start_dt + relativedelta(months=1)
                cycle_length_days = max(
                    1, (next_cycle_dt.date() - cycle_start_dt.date()).days
                )
            except Exception:
                pass  # fall back to 30
        days_remaining = max(0, cycle_length_days - days_in_cycle)
        projected_remaining = avg_per_day * days_remaining
        full_cycle_pace = cycle_savings + projected_remaining

        # v4.3.0 Review L18: renamed from arbitrage_savings_pace_monthly which
        # implied "per month rolling" — the value is actually accrued+projected
        # for THIS bill cycle, which can be 28-31 days.
        attrs["arbitrage_savings_this_cycle"] = round(cycle_savings, 2)
        attrs["arbitrage_savings_projected_cycle_total"] = round(full_cycle_pace, 2)

        predicted = self.native_value  # already accounts for arbitrage having run
        if predicted is not None and full_cycle_pace > 0:
            without_arb = float(predicted) + full_cycle_pace
            attrs["predicted_bill_without_arbitrage"] = round(without_arb, 2)
            if without_arb > 0:
                attrs["arbitrage_savings_pct"] = round(
                    full_cycle_pace / without_arb * 100.0, 1,
                )
            attrs["arbitrage_methodology"] = (
                "v4.5.0: estimate is realistic within ±10% — phased timing "
                "(late-charge window + forecast re-check) minimizes wasted "
                "grid imports, and HOLD preserves the buffer until the "
                "high-rate window. Counterfactual assumes the locked buffer "
                "is fully discharged at the displaced rate."
            )

        # Energy Savings Unification (cycle #7): peak-avoidance + total attrs.
        # Additive — existing arbitrage attrs preserved above for consumer compat.
        try:
            pa_status = energy.peak_avoidance_status or {}
            pa_cycle = float(pa_status.get("peak_avoidance_cycle", 0.0))
            attrs["peak_avoidance_savings_this_cycle"] = round(pa_cycle, 2)
            total_cycle = float(
                attrs.get("arbitrage_savings_this_cycle", 0.0)
            ) + pa_cycle
            attrs["total_savings_this_cycle"] = round(total_cycle, 2)
            predicted = self.native_value
            if predicted is not None:
                # Combined counterfactual: bill without solar+battery = raw
                # predicted + BOTH savings components projected across cycle.
                # Peak-avoidance projection uses same avg-per-day shape as
                # arbitrage above (cycle_savings + avg_per_day × days_left).
                pa_avg_per_day = (
                    pa_cycle / max(days_in_cycle, 1) if days_in_cycle else 0.0
                )
                pa_projected_remaining = pa_avg_per_day * days_remaining
                pa_full_cycle = pa_cycle + pa_projected_remaining
                without_sb = (
                    float(predicted) + full_cycle_pace + pa_full_cycle
                )
                attrs["predicted_bill_without_solar_battery"] = round(without_sb, 2)
        except Exception:
            # B-MEDIUM-3 (fix-up): debug-log so shape regressions surface
            # in logs; still non-fatal — this sensor is display-only.
            _LOGGER.debug("PA predicted-bill attrs skipped", exc_info=True)
        return attrs or None


class EnergyArbitrageSavingsTodaySensor(AggregationEntity, SensorEntity):
    """v4.3.0 D4: Arbitrage savings since local midnight."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:cash-plus"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_arbitrage_savings_today"
        self._attr_name = "Arbitrage Savings Today"
        self._attr_device_info = _energy_device_info()

    def _get_today(self) -> dict[str, Any]:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return (energy.arbitrage_status or {}).get("today") or {}

    @property
    def native_value(self) -> float | None:
        return round(float(self._get_today().get("savings", 0.0)), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        today = self._get_today()
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        energy = manager.coordinators.get("energy") if manager else None
        last = (energy.arbitrage_status or {}).get("last_cycle") if energy else None
        attrs: dict[str, Any] = {
            "cycles_today": int(today.get("cycles", 0)),
            "kwh_charged_today": round(float(today.get("kwh_charged", 0.0)), 3),
            # v4.3.0 Review M9-C: honest disclosure of the optimism bias.
            # The savings figure assumes the charged kWh is later consumed at
            # the displaced rate (peak in summer, mid_peak in shoulder/winter).
            # If sun overproduces and the battery doesn't actually discharge
            # during peak, real savings are lower than reported.
            "methodology": (
                "v4.5.0: late-charge window + forecast re-check + HOLD "
                "preserves buffer to the displaced rate window. Counterfactual "
                "assumes the locked buffer is fully discharged at peak/mid_peak. "
                "Estimate accuracy ±10% on typical days."
            ),
        }
        if last is not None:
            attrs.update({
                "last_cycle_at": last.get("timestamp"),
                "last_cycle_kwh_charged": round(float(last.get("kwh_charged", 0.0)), 3),
                "last_cycle_off_peak_rate": last.get("off_peak_rate"),
                "last_cycle_displaced_rate": last.get("displaced_rate"),
                "last_cycle_round_trip_efficiency": last.get("round_trip_efficiency"),
                "last_cycle_savings": round(float(last.get("savings", 0.0)), 4),
            })
        return attrs


class EnergyArbitrageSavingsCycleSensor(AggregationEntity, SensorEntity):
    """v4.3.0 D4: Arbitrage savings since bill cycle start."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:cash-multiple"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_arbitrage_savings_cycle"
        self._attr_name = "Arbitrage Savings This Cycle"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        cycle = (energy.arbitrage_status or {}).get("cycle") or {}
        return round(float(cycle.get("savings", 0.0)), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        cycle = (energy.arbitrage_status or {}).get("cycle") or {}
        pace = (energy.arbitrage_status or {}).get("pace") or {}
        return {
            "cycles_this_cycle": int(cycle.get("cycles", 0)),
            "kwh_charged_this_cycle": round(float(cycle.get("kwh_charged", 0.0)), 3),
            "avg_savings_per_day_7d": round(
                float(pace.get("avg_savings_per_day", 0.0)), 4,
            ),
            "days_with_cycles_in_lookback": int(pace.get("days_with_cycles", 0)),
            "methodology": (
                "v4.5.0: phased timing + HOLD preserves buffer. Counterfactual "
                "assumes the locked buffer is fully discharged at the "
                "displaced rate window. Estimate accuracy ±10% on typical days."
            ),
        }


class EnergyArbitrageSavingsTotalSensor(AggregationEntity, SensorEntity):
    """v4.3.0 D4: Lifetime arbitrage savings since v4.3.0 deploy.

    v4.6.10 D6: state_class TOTAL_INCREASING → TOTAL (MONETARY + TOTAL_INCREASING
    rejected by HA recorder).  TOTAL is correct for lifetime accumulators.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:cash-100"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_arbitrage_savings_total"
        self._attr_name = "Arbitrage Savings Total"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        total = (energy.arbitrage_status or {}).get("total") or {}
        return round(float(total.get("savings", 0.0)), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        total = (energy.arbitrage_status or {}).get("total") or {}
        return {
            "total_cycles": int(total.get("cycles", 0)),
            "total_kwh_charged": round(float(total.get("kwh_charged", 0.0)), 3),
            "round_trip_efficiency_assumption": energy.arbitrage_round_trip_efficiency,
            "methodology": (
                "v4.5.0: lifetime projected savings; each cycle assumes the "
                "locked buffer is fully discharged at the displaced rate. "
                "Phased state machine (CHARGE → HOLD) preserves the buffer "
                "until the high-rate window — minimizing pre-arbitrage waste. "
                "Estimate accuracy ±10% per cycle; lifetime drift bounded."
            ),
        }


# ============================================================================
# Energy Savings Unification (cycle #7) — display-only savings family
# ============================================================================
# Additive family, alongside the existing 3 arbitrage_savings sensors (no
# rename). Total_{scope} = arbitrage_{scope} + peak_avoidance_{scope}, computed
# at read time (single source of truth). All USD, MONETARY, state_class TOTAL.


def _ec(hass: HomeAssistant):
    manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
    if manager is None:
        return None
    return manager.coordinators.get("energy")


def _arb_scope(hass: HomeAssistant, scope: str) -> float:
    """Return arbitrage savings ($) for scope in {today, cycle, total}."""
    ec = _ec(hass)
    if ec is None:
        return 0.0
    data = (ec.arbitrage_status or {}).get(scope) or {}
    return float(data.get("savings", 0.0))


def _arb_kwh_scope(hass: HomeAssistant, scope: str) -> float:
    ec = _ec(hass)
    if ec is None:
        return 0.0
    data = (ec.arbitrage_status or {}).get(scope) or {}
    return float(data.get("kwh_charged", 0.0))


class _SavingsSensorBase(AggregationEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_device_info = _energy_device_info()


class EnergySavingsPeakAvoidanceTodaySensor(_SavingsSensorBase):
    """Peak-avoidance $ saved since local midnight.

    Entity: sensor.ura_energy_savings_peak_avoidance_today
    """
    _attr_icon = "mdi:solar-power"

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_savings_peak_avoidance_today"
        self._attr_name = "Energy Savings — Peak Avoidance Today"

    @property
    def native_value(self) -> float | None:
        ec = _ec(self.hass)
        if ec is None:
            return None
        return round(ec.peak_avoidance_status.get("peak_avoidance_today", 0.0), 2)

    @property
    def extra_state_attributes(self) -> dict:
        ec = _ec(self.hass)
        if ec is None:
            return {}
        st = ec.peak_avoidance_status
        return {
            "kwh_avoided_today": st.get("kwh_avoided_today"),
            "peak_avoidance_methodology": st.get("methodology"),
        }


class EnergySavingsPeakAvoidanceBillingCycleSensor(_SavingsSensorBase):
    """Peak-avoidance $ saved since billing-cycle start.

    Entity: sensor.ura_energy_savings_peak_avoidance_billing_cycle
    """
    _attr_icon = "mdi:solar-power-variant"

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = (
            f"{DOMAIN}_energy_savings_peak_avoidance_billing_cycle"
        )
        self._attr_name = "Energy Savings — Peak Avoidance This Cycle"

    @property
    def native_value(self) -> float | None:
        ec = _ec(self.hass)
        if ec is None:
            return None
        return round(ec.peak_avoidance_status.get("peak_avoidance_cycle", 0.0), 2)

    @property
    def extra_state_attributes(self) -> dict:
        ec = _ec(self.hass)
        if ec is None:
            return {}
        st = ec.peak_avoidance_status
        return {
            "kwh_avoided_billing_cycle": st.get("kwh_avoided_cycle"),
            "peak_avoidance_methodology": st.get("methodology"),
        }


class EnergySavingsPeakAvoidanceLifetimeSensor(_SavingsSensorBase):
    """Lifetime peak-avoidance $ (= baseline + delta-since-baseline).

    Entity: sensor.ura_energy_savings_peak_avoidance_lifetime
    """
    _attr_icon = "mdi:solar-panel-large"

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_savings_peak_avoidance_lifetime"
        self._attr_name = "Energy Savings — Peak Avoidance Lifetime"

    @property
    def native_value(self) -> float | None:
        ec = _ec(self.hass)
        if ec is None:
            return None
        baseline = float(
            (ec.savings_baselines.get("peak_avoidance") or {}).get("baseline_usd", 0.0)
        )
        delta = float(
            ec.peak_avoidance_status.get("peak_avoidance_lifetime_delta", 0.0)
        )
        return round(baseline + delta, 2)

    @property
    def extra_state_attributes(self) -> dict:
        ec = _ec(self.hass)
        if ec is None:
            return {}
        b = ec.savings_baselines.get("peak_avoidance") or {}
        st = ec.peak_avoidance_status
        return {
            "baseline_usd": b.get("baseline_usd"),
            "baseline_since": b.get("first_recorded_iso"),
            "delta_since_baseline_usd": st.get("peak_avoidance_lifetime_delta"),
            "peak_avoidance_methodology": st.get("methodology"),
        }


class EnergySavingsTotalTodaySensor(_SavingsSensorBase):
    """Total (arbitrage + peak-avoidance) $ saved today.

    Entity: sensor.ura_energy_savings_total_today
    """
    _attr_icon = "mdi:cash-plus"

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_savings_total_today"
        self._attr_name = "Energy Savings — Total Today"

    @property
    def native_value(self) -> float | None:
        ec = _ec(self.hass)
        if ec is None:
            return None
        arb = _arb_scope(self.hass, "today")
        pa = float(ec.peak_avoidance_status.get("peak_avoidance_today", 0.0))
        return round(arb + pa, 2)

    @property
    def extra_state_attributes(self) -> dict:
        ec = _ec(self.hass)
        if ec is None:
            return {}
        return {
            "arbitrage_component_usd": round(_arb_scope(self.hass, "today"), 4),
            "peak_avoidance_component_usd": round(
                float(ec.peak_avoidance_status.get("peak_avoidance_today", 0.0)), 4,
            ),
        }


class EnergySavingsTotalBillingCycleSensor(_SavingsSensorBase):
    """Total savings $ so far this billing cycle.

    Entity: sensor.ura_energy_savings_total_billing_cycle
    """
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_savings_total_billing_cycle"
        self._attr_name = "Energy Savings — Total This Cycle"

    @property
    def native_value(self) -> float | None:
        ec = _ec(self.hass)
        if ec is None:
            return None
        arb = _arb_scope(self.hass, "cycle")
        pa = float(ec.peak_avoidance_status.get("peak_avoidance_cycle", 0.0))
        return round(arb + pa, 2)

    @property
    def extra_state_attributes(self) -> dict:
        ec = _ec(self.hass)
        if ec is None:
            return {}
        return {
            "arbitrage_component_usd": round(_arb_scope(self.hass, "cycle"), 4),
            "peak_avoidance_component_usd": round(
                float(ec.peak_avoidance_status.get("peak_avoidance_cycle", 0.0)), 4,
            ),
        }


class EnergySavingsTotalLifetimeSensor(_SavingsSensorBase):
    """Lifetime total savings $ (arbitrage lifetime + peak-avoidance lifetime).

    Entity: sensor.ura_energy_savings_total_lifetime
    """
    _attr_icon = "mdi:cash-100"

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_savings_total_lifetime"
        self._attr_name = "Energy Savings — Total Lifetime"

    def _arb_lifetime(self) -> float:
        ec = _ec(self.hass)
        if ec is None:
            return 0.0
        baseline = float(
            (ec.savings_baselines.get("arbitrage") or {}).get("baseline_usd", 0.0)
        )
        # Existing arbitrage_status['total'] queries the FULL arbitrage_cycles
        # table (which includes pre-baseline rows). To honor baseline
        # semantics AND survive prune, take max(baseline, live_total): while
        # rows are intact live_total >= baseline (baseline was seeded from
        # live_total); after a prune live_total drops but max() preserves
        # baseline. This is the "min-guarantee" shape the plan calls for.
        live_total = _arb_scope(self.hass, "total")
        return max(baseline, live_total)

    @property
    def native_value(self) -> float | None:
        ec = _ec(self.hass)
        if ec is None:
            return None
        pa_baseline = float(
            (ec.savings_baselines.get("peak_avoidance") or {}).get(
                "baseline_usd", 0.0
            )
        )
        pa_delta = float(
            ec.peak_avoidance_status.get("peak_avoidance_lifetime_delta", 0.0)
        )
        return round(self._arb_lifetime() + pa_baseline + pa_delta, 2)

    @property
    def extra_state_attributes(self) -> dict:
        ec = _ec(self.hass)
        if ec is None:
            return {}
        return {
            "arbitrage_lifetime_usd": round(self._arb_lifetime(), 2),
            "peak_avoidance_lifetime_usd": round(
                float(
                    (ec.savings_baselines.get("peak_avoidance") or {}).get(
                        "baseline_usd", 0.0
                    )
                )
                + float(
                    ec.peak_avoidance_status.get(
                        "peak_avoidance_lifetime_delta", 0.0
                    )
                ),
                2,
            ),
        }


# ---- kWh-avoided (energy side of the same story) --------------------------


class _KwhAvoidedBase(AggregationEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:lightning-bolt-outline"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 3

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_device_info = _energy_device_info()


class EnergyKwhAvoidedTodaySensor(_KwhAvoidedBase):
    """kWh avoided (served locally instead of imported) since midnight.

    Entity: sensor.ura_energy_kwh_avoided_today
    """

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_kwh_avoided_today"
        self._attr_name = "Energy kWh Avoided Today"

    @property
    def native_value(self) -> float | None:
        ec = _ec(self.hass)
        if ec is None:
            return None
        return round(ec.peak_avoidance_status.get("kwh_avoided_today", 0.0), 3)


class EnergyKwhAvoidedBillingCycleSensor(_KwhAvoidedBase):
    """kWh avoided since billing-cycle start.

    Entity: sensor.ura_energy_kwh_avoided_billing_cycle
    """

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_kwh_avoided_billing_cycle"
        self._attr_name = "Energy kWh Avoided This Cycle"

    @property
    def native_value(self) -> float | None:
        ec = _ec(self.hass)
        if ec is None:
            return None
        return round(ec.peak_avoidance_status.get("kwh_avoided_cycle", 0.0), 3)


class EnergyKwhAvoidedLifetimeSensor(_KwhAvoidedBase):
    """Lifetime kWh avoided (baseline + delta-since-baseline).

    Entity: sensor.ura_energy_kwh_avoided_lifetime
    """

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_kwh_avoided_lifetime"
        self._attr_name = "Energy kWh Avoided Lifetime"

    @property
    def native_value(self) -> float | None:
        ec = _ec(self.hass)
        if ec is None:
            return None
        baseline = float(
            (ec.savings_baselines.get("kwh_avoided") or {}).get("baseline_kwh", 0.0)
        )
        delta = float(
            ec.peak_avoidance_status.get("kwh_avoided_lifetime_delta", 0.0)
        )
        return round(baseline + delta, 3)

    @property
    def extra_state_attributes(self) -> dict:
        ec = _ec(self.hass)
        if ec is None:
            return {}
        b = ec.savings_baselines.get("kwh_avoided") or {}
        return {
            "baseline_kwh": b.get("baseline_kwh"),
            "baseline_since": b.get("first_recorded_iso"),
        }


class EnergyCurrentRateSensor(AggregationEntity, SensorEntity):
    """Current effective import rate.

    Entity: sensor.ura_energy_current_rate
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:currency-usd"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_suggested_display_precision = 4

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_current_rate"
        self._attr_name = "Actual Energy Rate"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return round(energy.current_effective_rate, 6)


class EnergyDeliveryRateSensor(AggregationEntity, SensorEntity):
    """Delivery + transmission rate per kWh (non-commodity charges).

    Entity: sensor.ura_energy_delivery_rate
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:truck-delivery"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "$/kWh"
    _attr_suggested_display_precision = 4

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_delivery_rate"
        self._attr_name = "Delivery Rate"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return round(energy.delivery_rate, 6)


class EnergyImportTodaySensor(AggregationEntity, SensorEntity):
    """Net grid exchange today (positive=import, negative=export).

    Entity: sensor.ura_energy_import_today
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:transmission-tower-import"
    _attr_device_class = SensorDeviceClass.ENERGY
    # v4.7.16.5 hotfix: was MEASUREMENT which HA platform rejects for
    # device_class=ENERGY. Use TOTAL (not TOTAL_INCREASING) because
    # native_value can go NEGATIVE on export-heavy days (import_kwh -
    # export_kwh). TOTAL allows decreases; TOTAL_INCREASING would log
    # a different warning each time the value dipped. Matches the
    # convention used by sibling net-energy sensors at lines 713, 773.
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_import_today"
        self._attr_name = "Energy Import Today"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        status = energy.billing_status
        import_kwh = status.get("import_kwh_today", 0)
        export_kwh = status.get("export_kwh_today", 0)
        return round(import_kwh - export_kwh, 3)

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        status = energy.billing_status
        return {
            "import_kwh": status.get("import_kwh_today"),
            "export_kwh": status.get("export_kwh_today"),
            "import_cost": status.get("import_cost_today"),
            "export_credit": status.get("export_credit_today"),
            "net_cost": status.get("cost_today"),
        }


class EnergyExportTodaySensor(AggregationEntity, SensorEntity):
    """Export kWh today.

    Entity: sensor.ura_energy_export_today
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:transmission-tower-export"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_export_today"
        self._attr_name = "Energy Export Today"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.billing_status.get("export_kwh_today")

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return {"credit": energy.billing_status.get("export_credit_today")}


# ============================================================================
# v3.7.0-E5: FORECAST SENSORS
# ============================================================================


class EnergyForecastTodaySensor(AggregationEntity, SensorEntity):
    """Predicted net energy today (positive=export, negative=import).

    Entity: sensor.ura_energy_forecast_today
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:chart-line"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 1

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_forecast_today"
        self._attr_name = "Predicted Net Energy"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.forecast_today.get("predicted_net_kwh")

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return energy.forecast_today


class EnergyForecastedImportSensor(AggregationEntity, SensorEntity):
    """Predicted grid draw today accounting for battery buffering.

    On sunny days with a full battery, this is near zero because the
    battery covers nighttime consumption.  On cloudy days the shortfall
    comes from the grid.

    Entity: sensor.ura_energy_forecasted_import
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:transmission-tower-import"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 1

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_forecasted_import"
        self._attr_name = "Predicted Grid Import"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.predicted_import_kwh

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        forecast = energy.forecast_today
        return {
            "predicted_consumption_kwh": forecast.get("predicted_consumption_kwh"),
            "predicted_production_kwh": forecast.get("predicted_production_kwh"),
            "battery_capacity_kwh": energy._predictor._get_battery_capacity_kwh(),
            "reserve_soc_pct": energy._battery.reserve_soc,
            "usable_battery_kwh": round(
                energy._predictor._get_battery_capacity_kwh()
                * (1.0 - energy._battery.reserve_soc / 100.0), 1
            ),
            "battery_full_time": forecast.get("battery_full_time"),
        }


class EnergyForecastedConsumptionSensor(AggregationEntity, SensorEntity):
    """Predicted total home consumption today (kWh).

    Entity: sensor.ura_energy_forecasted_consumption
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-lightning-bolt"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kWh"
    _attr_suggested_display_precision = 1

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_forecasted_consumption"
        self._attr_name = "Forecasted Consumption"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.predicted_consumption_kwh


class EnergyBatteryFullTimeSensor(AggregationEntity, SensorEntity):
    """Estimated time battery reaches 100%.

    Entity: sensor.ura_energy_battery_full_time
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:battery-clock"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_battery_full_time"
        self._attr_name = "Battery Full Time"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.battery_full_time

    @property
    def extra_state_attributes(self) -> dict:
        # v5.16.1 H2 follow-up: surface the predictor's basis/rate/taper
        # attrs (were computed but never exposed — Bug Class #55).
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        try:
            return energy.battery_full_time_attrs
        except Exception:  # noqa: BLE001
            return {}


class EnergyForecastAccuracySensor(AggregationEntity, SensorEntity):
    """Forecast accuracy (7-day rolling %).

    Entity: sensor.ura_energy_forecast_accuracy
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:target"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_suggested_display_precision = 1

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_forecast_accuracy"
        self._attr_name = "Forecast Accuracy"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        accuracy = energy.forecast_accuracy
        return accuracy if accuracy > 0 else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        status = energy._accuracy.get_status()
        samples = status.get("samples", 0)
        return {
            "samples": samples,
            "status": "learning" if samples < 3 else "active",
            "adjustment_factor": status.get("adjustment_factor", 1.0),
            "last_eval_date": status.get("last_eval_date", ""),
        }


# ============================================================================
# v3.7.0-E6: SITUATION + CONSTRAINT SENSORS
# ============================================================================


class EnergySituationSensor(AggregationEntity, SensorEntity):
    """Overall energy situation.

    Entity: sensor.ura_energy_situation
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_situation"
        self._attr_name = "Energy Situation"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "unknown"
        return energy.energy_situation


class EnergyHVACConstraintSensor(AggregationEntity, SensorEntity):
    """Current HVAC constraint mode for future HVAC coordinator.

    Entity: sensor.ura_hvac_constraint
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:thermostat"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_constraint"
        self._attr_name = "HVAC Constraint"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "normal"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "normal"
        return energy.hvac_constraint.get("mode", "normal")

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return energy.hvac_constraint


# ============================================================================
# v3.7.7: CONSUMPTION + EV MONITORING SENSORS
# ============================================================================


class EnergyTotalConsumptionSensor(AggregationEntity, SensorEntity):
    """Total home consumption from Envoy CT clamp (ground truth).

    Entity: sensor.ura_energy_total_consumption
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-lightning-bolt"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kW"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_total_consumption"
        self._attr_name = "Total Consumption"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        # Unit-correctness: this sensor declares kW, so derive true kW from
        # the uom-normalized total_consumption_w property (always W) — NOT
        # the historically mis-named total_consumption_kw, which returns the
        # raw entity state (W or kW depending on firmware) and would display
        # a 1000x-too-large number on W-reporting Envoys.
        consumption_w = energy.total_consumption_w
        return consumption_w / 1000.0 if consumption_w is not None else None


class EnergyNetConsumptionSensor(AggregationEntity, SensorEntity):
    """Net consumption (positive=importing from grid, negative=exporting).

    Entity: sensor.ura_energy_net_consumption
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:transmission-tower"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kW"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_net_consumption"
        self._attr_name = "Net Consumption"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        # Unit-correctness: this sensor declares kW, so derive true kW from
        # the uom-normalized net_power_w property (positive=importing, always
        # W) — NOT net_consumption_kw, which returns the raw battery.net_power
        # entity (W or kW depending on firmware) and would mislabel by 1000x
        # on W-reporting Envoys.
        net_w = energy._battery.net_power_w
        return net_w / 1000.0 if net_w is not None else None


class EnergyEVChargeRateASensor(AggregationEntity, SensorEntity):
    """EVSE Garage A charge rate in watts.

    Entity: sensor.ura_energy_ev_charge_rate_garage_a
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:ev-station"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_suggested_display_precision = 0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_ev_charge_rate_garage_a"
        self._attr_name = "EV Charge Rate Garage A"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.evse_garage_a_power


class EnergyEVChargeRateBSensor(AggregationEntity, SensorEntity):
    """EVSE Garage B charge rate in watts.

    Entity: sensor.ura_energy_ev_charge_rate_garage_b
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:ev-station"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"
    _attr_suggested_display_precision = 0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_ev_charge_rate_garage_b"
        self._attr_name = "EV Charge Rate Garage B"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> float | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.evse_garage_b_power


# ============================================================================
# v3.8.0-H1: HVAC COORDINATOR SENSORS
# ============================================================================


def _hvac_device_info():
    """Return device info for HVAC Coordinator sensors."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, "hvac_coordinator")},
        name="URA: HVAC Coordinator",
        manufacturer="Universal Room Automation",
        model="HVAC Coordinator",
        sw_version=VERSION,
        via_device=(DOMAIN, "coordinator_manager"),
    )


class HVACModeSensor(AggregationEntity, SensorEntity):
    """HVAC operating mode.

    Entity: sensor.ura_hvac_coordinator_mode
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermostat"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_mode"
        self._attr_name = "10 · Mode"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        return hvac.get_mode()

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        return hvac.get_mode_attrs()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_schedule_update_ha_state()


class HVACZoneStatusSensor(AggregationEntity, SensorEntity):
    """Per-zone HVAC status.

    Entity: sensor.ura_hvac_coordinator_zone_{n}_status
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, zone_id: str
    ) -> None:
        super().__init__(hass, entry)
        self._zone_id = zone_id
        zone_num = zone_id.split("_")[-1] if "_" in zone_id else zone_id
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_{zone_id}_status"
        self._attr_name = f"50 · Zone {zone_num} Status"
        self._attr_icon = "mdi:thermostat"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unavailable"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        zone = hvac.zone_manager.zones.get(self._zone_id)
        if zone is None:
            return "unknown"
        return zone.hvac_mode or "unknown"

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        return hvac.zone_manager.get_zone_status_attrs(self._zone_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_schedule_update_ha_state()


class HVACAnomalySensor(AggregationEntity, SensorEntity):
    """HVAC anomaly status.

    Entity: sensor.ura_hvac_coordinator_anomaly
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_anomaly"
        self._attr_name = "10 · HVAC Anomaly"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        return hvac.get_anomaly_status()

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        if hvac.anomaly_detector is None:
            return {}
        return hvac.anomaly_detector.get_status_summary()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_schedule_update_ha_state()


class HVACComplianceSensor(AggregationEntity, SensorEntity):
    """HVAC compliance rate.

    Entity: sensor.ura_hvac_coordinator_compliance
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:check-decagram"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_compliance"
        self._attr_name = "15 · HVAC Compliance"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        summary = hvac.get_compliance_summary()
        return str(summary.get("overrides_today", 0))

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        return hvac.get_compliance_summary()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_schedule_update_ha_state()


class HVACOverrideFrequencySensor(AggregationEntity, SensorEntity):
    """HVAC override frequency — tracks overrides and AC resets today.

    Entity: sensor.ura_hvac_coordinator_override_frequency
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-octagon"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_override_frequency"
        self._attr_name = "20 · HVAC Override Frequency"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        status = hvac.override_arrester.get_override_status()
        return str(status.get("overrides_today", 0))

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        return hvac.override_arrester.get_override_status()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_schedule_update_ha_state()


class HVACPreCoolLikelihoodSensor(AggregationEntity, SensorEntity):
    """HVAC pre-cool likelihood percentage.

    Entity: sensor.ura_hvac_coordinator_pre_cool_likelihood
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:snowflake-alert"
    _attr_native_unit_of_measurement = "%"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_pre_cool_likelihood"
        self._attr_name = "40 · HVAC Pre-Cool Likelihood"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> int:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return 0
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return 0
        return hvac.predictor.pre_cool_likelihood

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        # v4.6.9 D4: merge prediction attrs with intent enrichment attrs.
        # get_intent_attrs() returns the 6 D4 keys (all str/float/int/None — no
        # nested dicts, no Decimal, no "—" strings); Bug Class #37 contract for
        # the D4 keys is flat.
        # Tier 2-DB Reviewer C H1: NOTE that the pre-existing
        # `get_prediction_attrs()` already returns `zone_demand: dict[str,str]`
        # — that is one nested dict that pre-dates v4.6.9 and is consumed by
        # other PWA surfaces; we don't strip it. So the merged result is NOT
        # uniformly flat (one nested key, plus 6 + ~6 flat keys). PWA
        # `useUraSensorAttrs<HvacIntentAttrs>` reads only the 6 D4 keys.
        attrs = dict(hvac.predictor.get_prediction_attrs())
        try:
            intent = hvac.predictor.get_intent_attrs()
            attrs.update(intent)
        except Exception:  # noqa: BLE001
            # Defensive guard: if intent attrs fail for any reason, the base
            # prediction attrs are still returned intact.
            pass
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_schedule_update_ha_state()


class HVACComfortRiskSensor(AggregationEntity, SensorEntity):
    """HVAC comfort violation risk level.

    Entity: sensor.ura_hvac_coordinator_comfort_risk
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermometer-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_comfort_risk"
        self._attr_name = "30 · HVAC Comfort Risk"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "unknown"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        return hvac.predictor.comfort_violation_risk

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        return hvac.predictor.get_outcome_attrs()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_schedule_update_ha_state()


# ============================================================================
# v3.9.0-E6: ENERGY TRANSPARENCY SENSORS
# ============================================================================


class EnergyBatteryDecisionSensor(AggregationEntity, SensorEntity):
    """Last battery strategy decision and reason.

    Entity: sensor.ura_energy_battery_decision
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:battery-sync"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_battery_decision"
        self._attr_name = "Battery Decision"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "disabled"
        decision = energy.battery_decision_status
        return decision.get("mode", "unknown") if decision else "unknown"

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        status = energy.battery_decision_status or {}
        # Filter internal actions list — not useful as sensor attributes
        return {k: v for k, v in status.items() if k != "actions"}


class EnergyLoadSheddingSensor(AggregationEntity, SensorEntity):
    """Load shedding status — active level and shed loads.

    Entity: sensor.ura_energy_load_shedding
    Device: URA: Energy Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:power-plug-off"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_load_shedding"
        self._attr_name = "Load Shedding"
        self._attr_device_info = _energy_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        energy = manager.coordinators.get("energy")
        if energy is None:
            return "disabled"
        status = energy.load_shedding_status
        if not status.get("enabled"):
            return "disabled"
        if status.get("active"):
            return f"level_{status['level']}"
        return "idle"

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        return energy.load_shedding_status


# ============================================================================
# v3.9.0: HVAC TRANSPARENCY SENSORS
# ============================================================================


class HVACArresterStateSensor(AggregationEntity, SensorEntity):
    """Override arrester state — idle, grace_period, compromise, reverting, disabled.

    Entity: sensor.ura_hvac_arrester_state
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_arrester_state"
        self._attr_name = "25 · Override Arrester State"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        return hvac.override_arrester.get_arrester_state()

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        return hvac.override_arrester.get_arrester_detail()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_schedule_update_ha_state()


class HVACZonePresetSensor(AggregationEntity, SensorEntity):
    """Per-zone preset diagnostic — shows current target preset and setpoints.

    Entity: sensor.ura_hvac_zone_preset_{zone_id}
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermostat-box"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, zone_id: str) -> None:
        super().__init__(hass, entry)
        self._zone_id = zone_id
        self._attr_unique_id = f"{DOMAIN}_hvac_zone_preset_{zone_id}"
        self._attr_name = f"55 · HVAC Zone Preset {zone_id.replace('_', ' ').title()}"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return "not_initialized"
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return "disabled"
        zone = hvac.zone_manager.zones.get(self._zone_id)
        if zone is None:
            return "unknown"
        return zone.preset_mode or "none"

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        zone = hvac.zone_manager.zones.get(self._zone_id)
        if zone is None:
            return {}
        attrs = {
            "zone_name": zone.zone_name,
            "climate_entity": zone.climate_entity,
            "preset_mode": zone.preset_mode,
            "target_temp_high": zone.target_temp_high,
            "target_temp_low": zone.target_temp_low,
            "current_temperature": zone.current_temperature,
            "hvac_mode": zone.hvac_mode,
            "hvac_action": zone.hvac_action,
            "overrides_today": zone.override_count_today,
            "ac_resets_today": zone.ac_reset_count_today,
        }
        if zone.last_override_direction:
            attrs["last_override_direction"] = zone.last_override_direction
        # Add seasonal preset target from PresetManager
        season = hvac.preset_manager.current_season
        if season:
            attrs["season"] = season
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_preset_update
            )
        )

    @callback
    def _handle_preset_update(self) -> None:
        self.async_schedule_update_ha_state()


# ============================================================================
# v4.5.12 D7: Per-zone AC ramp-down state sensors (3 per AC zone)
# ============================================================================
# These surface what slice 1's OverrideArrester is doing for each AC zone:
#   - state machine state (idle/detecting/nudging/awaiting_eval/escalating/
#                          locked_out/disabled)
#   - last action timestamp + attrs (what happened most recently)
#   - live kWh-rate from the configured ac_load_sensor (with staleness)
#
# All three look up the zone by climate_entity (not by zone_id) to bridge
# the v4.5.11.2 naming-convention drift — ZoneManager uses `zone_N` zone_ids
# while the platform-side derivation produces `<thermostat_name>` strings.
# Look up by climate_entity (stable, unique) instead.


class _ACRampZoneSensorMixin:
    """Shared lookup + refresh wiring for D7 per-zone sensors."""

    def _get_zone(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        hvac = manager.coordinators.get("hvac") if hasattr(manager, "coordinators") else None
        if hvac is None:
            return None
        zm = getattr(hvac, "_zone_manager", None) or getattr(hvac, "zone_manager", None)
        if zm is None:
            return None
        for z in zm.zones.values():
            if z.climate_entity == self._climate_entity:
                return z
        return None

    async def async_added_to_hass(self) -> None:
        """Subscribe to SIGNAL_HVAC_ENTITIES_UPDATE so the sensor refreshes
        on every HVAC decision tick (Bug Class #35 prevention pattern)."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_hvac_tick,
            )
        )

    @callback
    def _handle_hvac_tick(self, *_a, **_kw) -> None:
        self.async_schedule_update_ha_state()


class HVACACRampStateSensor(_ACRampZoneSensorMixin, AggregationEntity, SensorEntity):
    """v4.5.12 D7: per-zone AC ramp-down state machine label.

    Returns one of: idle / detecting / nudging / awaiting_evaluation /
    escalating / locked_out / disabled. The seven legal values are
    enumerated in `AC_RAMP_STATES` (hvac_const.py).

    Entity: sensor.ura_hvac_ac_ramp_state_<zone_id>
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:state-machine"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry,
        zone_id: str, zone_name: str, climate_entity: str,
    ) -> None:
        super().__init__(hass, entry)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._climate_entity = climate_entity
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_ramp_state_{zone_id}"
        self._attr_name = f"60 · AC Ramp State ({zone_name})"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> str:
        zone = self._get_zone()
        if zone is None:
            return "unavailable"
        # ramp_state is maintained by OverrideArrester slice 1 logic.
        # Always one of AC_RAMP_STATES values.
        return getattr(zone, "ramp_state", "idle") or "idle"

    @property
    def extra_state_attributes(self) -> dict:
        zone = self._get_zone()
        if zone is None:
            return {}
        return {
            "zone_name": self._zone_name,
            "climate_entity": self._climate_entity,
            "kwh_samples_above_threshold": getattr(
                zone, "kwh_samples_above_threshold", 0,
            ),
            "last_overshoot_started": getattr(
                zone, "last_overshoot_started", "",
            ),
            "ac_load_sensor": getattr(zone, "ac_load_sensor", ""),
            "ramp_zone_enabled": getattr(zone, "ramp_zone_enabled", True),
        }


class HVACACRampLastActionSensor(
    _ACRampZoneSensorMixin, AggregationEntity, SensorEntity,
):
    """v4.5.12 D7: ISO timestamp of the most recent ramp-down action on
    this zone. Attrs carry the action type, triggered_by (auto/manual),
    and the kWh before/after if known.

    Read from ZoneState in-memory fields populated by OverrideArrester's
    `_track_zone_action` helper at every event-log site. No DB query
    on the read path (sensor would otherwise stress the write queue).

    Entity: sensor.ura_hvac_ac_ramp_last_action_<zone_id>
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:history"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry,
        zone_id: str, zone_name: str, climate_entity: str,
    ) -> None:
        super().__init__(hass, entry)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._climate_entity = climate_entity
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_ramp_last_action_{zone_id}"
        self._attr_name = f"62 · AC Ramp Last Action ({zone_name})"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self):
        zone = self._get_zone()
        if zone is None:
            return None
        ts = getattr(zone, "last_action_ts", "")
        if not ts:
            return None
        try:
            # SensorDeviceClass.TIMESTAMP requires a datetime
            from datetime import datetime
            return datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict:
        zone = self._get_zone()
        if zone is None:
            return {}
        return {
            "zone_name": self._zone_name,
            "climate_entity": self._climate_entity,
            "action_type": getattr(zone, "last_action_type", "") or "none",
            "triggered_by": getattr(
                zone, "last_action_triggered_by", "",
            ) or "none",
            "kwh_rate_before": getattr(zone, "last_action_kwh_before", None),
            "kwh_rate_after": getattr(zone, "last_action_kwh_after", None),
        }


class HVACACRampKwhRateSensor(
    _ACRampZoneSensorMixin, AggregationEntity, SensorEntity,
):
    """v4.5.12 D7 (v4.5.13 fix): live kW reading from this zone's `ac_load_sensor`.

    Reads directly from `hass.states.get(zone.ac_load_sensor)` and converts
    W -> kW based on the source unit. Independent of the AC ramp-down master
    switch — a diagnostic sensor should reflect the source's reality whether
    or not the ramp feature is gating writes to internal state.

    v4.5.12 read from `ZoneState.last_kwh_rate` which OverrideArrester only
    populates while the master switch is ON. With the switch OFF, the field
    stayed None and the sensor was stuck `unknown` even when the AC was
    drawing several kW. v4.5.13 removes that gate.

    The `stale` attribute is True when the source's last_updated is older
    than AC_KWH_SENSOR_STALENESS_S (default 10 min).

    Entity: sensor.ura_hvac_ac_ramp_kwh_rate_<zone_id>
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:flash"
    _attr_native_unit_of_measurement = "kW"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry,
        zone_id: str, zone_name: str, climate_entity: str,
    ) -> None:
        super().__init__(hass, entry)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._climate_entity = climate_entity
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_ramp_kwh_rate_{zone_id}"
        self._attr_name = f"64 · AC kWh Rate ({zone_name})"
        self._attr_device_info = _hvac_device_info()

    # Sanity bounds for residential AC compressor draw. Outside this band
    # the source sensor is almost certainly glitching (battery_power
    # kW/W glitch class — see TECH_DEBT history). We reject rather than
    # publish, so HA long-term statistics don't integrate the glitch.
    _MAX_PLAUSIBLE_KW = 50.0
    _MIN_PLAUSIBLE_KW = 0.0  # negative draw = sensor bug, not export

    def _read_source_kw(self):
        """Read the source AC load sensor and return kW as float, or None.

        Returns None when:
          - zone unknown / source unset / source state unknown/unavailable
          - non-numeric source state
          - unit_of_measurement not explicitly W or kW (empty unit is
            rejected — too easy to misinterpret a template sensor that
            forgot to declare units)
          - parsed value outside [_MIN_PLAUSIBLE_KW, _MAX_PLAUSIBLE_KW]
            (sensor glitch protection)

        Centralized so native_value and attribute computation share one
        parse path (and one set of edge-case guards).
        """
        zone = self._get_zone()
        if zone is None:
            return None, None
        source_entity = getattr(zone, "ac_load_sensor", None)
        if not source_entity:
            return zone, None
        state = self.hass.states.get(source_entity)
        if state is None or state.state in ("unknown", "unavailable", ""):
            return zone, None
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return zone, None
        unit = (state.attributes.get("unit_of_measurement") or "").strip()
        if unit == "W":
            value = value / 1000.0
        elif unit != "kW":
            # Unknown / missing unit — refuse to guess. A template sensor
            # without unit_of_measurement gets None rather than a
            # potentially-W-but-labeled-kW reading.
            return zone, None
        if value < self._MIN_PLAUSIBLE_KW or value > self._MAX_PLAUSIBLE_KW:
            return zone, None
        return zone, round(value, 3)

    @property
    def native_value(self):
        _zone, kw = self._read_source_kw()
        return kw

    @property
    def extra_state_attributes(self) -> dict:
        from datetime import timezone
        from .domain_coordinators.hvac_const import AC_KWH_SENSOR_STALENESS_S
        zone, _kw = self._read_source_kw()
        if zone is None:
            return {}
        source_entity = getattr(zone, "ac_load_sensor", "") or ""
        last_ts = None
        age_s = None
        stale = True
        source_unit = None
        if source_entity:
            state = self.hass.states.get(source_entity)
            if state is not None:
                last_updated = getattr(state, "last_updated", None)
                if last_updated is not None:
                    last_ts = last_updated.isoformat()
                    age_s = (
                        datetime.now(timezone.utc) - last_updated
                    ).total_seconds()
                    stale = age_s > AC_KWH_SENSOR_STALENESS_S
                source_unit = state.attributes.get("unit_of_measurement")
        return {
            "zone_name": self._zone_name,
            "climate_entity": self._climate_entity,
            "source_entity": source_entity or "unset",
            "source_unit": source_unit,
            "last_updated": last_ts,
            "age_seconds": int(age_s) if age_s is not None else None,
            "stale": stale,
            "kwh_threshold": getattr(zone, "kwh_rate_threshold", 0.8),
        }


# ============================================================================
# v4.5.12 D8: House-wide AC ramp-down impact sensors (5)
# ============================================================================
# These surface the cumulative effect of the AC ramp-down feature:
#   - nudges_today / resets_today (count of soft + hard interventions)
#   - kwh_avoided_today / _total (rough estimate — see TECH_DEBT.md)
#   - false_positive_rate (% of nudges where kwh_rate didn't drop)
#
# All read from `OverrideArrester._impact_cache`, refreshed once per
# decision cycle (5 min) at the end of check_ac_reset. Sync read path
# from the sensor — no DB query on every state poll.
#
# All five subscribe to SIGNAL_HVAC_ENTITIES_UPDATE (Bug Class #35
# prevention) so they auto-refresh per cycle without needing manual
# update_entity calls.


class _ACRampImpactSensorMixin:
    """Shared cache lookup + refresh signal for D8 house-wide sensors."""

    def _get_cache(self) -> dict | None:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        hvac = manager.coordinators.get("hvac") if hasattr(manager, "coordinators") else None
        if hvac is None:
            return None
        arr = getattr(hvac, "_override_arrester", None)
        if arr is None:
            return None
        return getattr(arr, "_impact_cache", None)

    async def async_added_to_hass(self) -> None:
        """Refresh on every HVAC tick (Bug Class #35 prevention)."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_hvac_tick,
            )
        )

    @callback
    def _handle_hvac_tick(self, *_a, **_kw) -> None:
        self.async_schedule_update_ha_state()


class HVACACNudgesTodaySensor(
    _ACRampImpactSensorMixin, AggregationEntity, SensorEntity,
):
    """v4.5.12 D8: count of soft nudges fired today (across all zones).

    Resets at midnight via the DB's date-keyed ac_reset_state table.

    Entity: sensor.ura_hvac_ac_nudges_today
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:thermometer-chevron-up"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "nudges"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_nudges_today"
        self._attr_name = "50 · AC Nudges Today"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> int:
        cache = self._get_cache()
        if cache is None:
            return 0
        return int(cache.get("nudges_today", 0))

    @property
    def extra_state_attributes(self) -> dict:
        cache = self._get_cache()
        if cache is None:
            return {}
        return {"last_refresh_ts": cache.get("last_refresh_ts")}


class HVACACResetsTodaySensor(
    _ACRampImpactSensorMixin, AggregationEntity, SensorEntity,
):
    """v4.5.12 D8: count of hard resets fired today (across all zones).

    Hard resets are the compressor-protection escalation path. Daily
    cap is 2 per zone — so 6 max house-wide (3 zones × 2). If this
    sensor approaches the cap, investigate.

    Entity: sensor.ura_hvac_ac_resets_today
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:restart-alert"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "resets"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_resets_today"
        self._attr_name = "60 · AC Hard Resets Today"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> int:
        cache = self._get_cache()
        if cache is None:
            return 0
        return int(cache.get("resets_today", 0))


class HVACACKwhAvoidedTodaySensor(
    _ACRampImpactSensorMixin, AggregationEntity, SensorEntity,
):
    """v4.5.12 D8: daily accumulator of kWh avoided by AC ramp-down since
    local midnight.

    **NOT a precision instrument.** See docs/TECH_DEBT.md for the math.
    Each nudge_evaluated event stores its own per-event kwh_avoided at
    log time; this sensor sums those persisted per-event values across
    events whose `timestamp >= start_of_local_day()`. Properties:
      - monotonic non-decreasing within a day (state_class total_increasing)
      - resets to 0 at local midnight (rows fall out of the WHERE clause)
      - restart-safe: value is re-derived from ac_ramp_events, no RAM state

    Prior implementation used a rolling 24h window (`days=1`) which caused
    non-monotonic decreases as events aged out — see hvac_override.py.

    Entity: sensor.ura_hvac_ac_kwh_avoided_today
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:flash-off"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_kwh_avoided_today"
        self._attr_name = "70 · AC kWh Avoided Today"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> float:
        cache = self._get_cache()
        if cache is None:
            return 0.0
        return float(cache.get("kwh_avoided_today", 0.0))

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "accuracy": "rough_estimate",
            "accuracy_note": (
                "Sum of per-event kwh_avoided (kW-delta × capped 30-min "
                "projection recorded at nudge-eval time) for events since "
                "local midnight. Monotonic within-day, resets at 00:00 local. "
                "Trend-watching only; not billing-grade. See docs/TECH_DEBT.md."
            ),
        }


class HVACACKwhAvoidedTotalSensor(
    _ACRampImpactSensorMixin, AggregationEntity, SensorEntity, RestoreEntity,
):
    """v4.5.12 D8: cumulative kWh avoided since the AC ramp-down feature
    was first enabled. Persists across HA restart (RestoreEntity).

    Same rough-estimate caveat as the today sensor.

    Entity: sensor.ura_hvac_ac_kwh_avoided_total
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:flash-off-outline"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_kwh_avoided_total"
        self._attr_name = "80 · AC kWh Avoided (Total)"
        self._attr_device_info = _hvac_device_info()
        self._restored_value: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if (
            last_state is not None
            and last_state.state not in (None, "unknown", "unavailable")
        ):
            try:
                self._restored_value = float(last_state.state)
            except (ValueError, TypeError):
                self._restored_value = None

    @property
    def native_value(self) -> float:
        cache = self._get_cache()
        if cache is None:
            # Fall back to the last persisted value while coord is starting
            return self._restored_value if self._restored_value is not None else 0.0
        # Live cache wins once it's populated
        return float(cache.get("kwh_avoided_total", 0.0))

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "accuracy": "rough_estimate",
            "accuracy_note": (
                "Cumulative since feature enable. Trend-watching only; "
                "not billing-grade. See docs/TECH_DEBT.md."
            ),
        }


class HVACACKwhAvoidedBillingCycleSensor(
    _ACRampImpactSensorMixin, AggregationEntity, SensorEntity,
):
    """PLANNING_hvac_kwh_avoided_savings D1: kWh avoided by AC ramp-down since
    the current billing-cycle start (mirrors EC billing_cycle scope).

    Rough estimate; not billing-grade — same caveat as the today/total kWh
    sensors. Restart-safe via DB re-derive; no RAM state.

    Entity: sensor.ura_hvac_ac_kwh_avoided_billing_cycle
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:flash-off"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_kwh_avoided_billing_cycle"
        self._attr_name = "75 · AC kWh Avoided This Cycle"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> float:
        cache = self._get_cache()
        if cache is None:
            return 0.0
        return float(cache.get("kwh_avoided_cycle", 0.0))

    @property
    def extra_state_attributes(self) -> dict:
        cache = self._get_cache() or {}
        return {
            "accuracy": "rough_estimate",
            "accuracy_note": (
                "Sum of per-event kwh_avoided since billing-cycle start "
                "(mirrors EC billing_cycle boundary). Trend-watching only; "
                "not billing-grade. See docs/TECH_DEBT.md."
            ),
            # Review B L1: expose whether the cycle boundary came from the
            # EC public accessor or the local-midnight fallback, so a
            # degraded EC lookup is observable to operators.
            "cycle_start_source": cache.get("cycle_start_source", "unknown"),
        }


# ============================================================================
# PLANNING_hvac_kwh_avoided_savings D2: standalone AC-ramp $ savings family
# ============================================================================
# Rough estimate. Each nudge_evaluated event's persisted `kwh_avoided` is
# valued at the TOU-effective rate captured into `notes` at nudge-eval time
# (key `rate=<float>`). Forward-only: pre-deploy events without a captured
# rate contribute kWh but $0.
#
# CRITICAL DESIGN: these 3 sensors are their OWN family. They are NOT summed
# into EC `sensor.ura_energy_savings_total_*` (that family sums
# arbitrage + peak_avoidance only — see EnergySavingsTotal{Today,BillingCycle,
# Lifetime}Sensor above). Folding AC-ramp $ into total_savings would double-
# count against peak-avoidance/arbitrage on the same avoided kWh.


class _ACRampSavingsSensorBase(
    _ACRampImpactSensorMixin, AggregationEntity, SensorEntity,
):
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_device_info = _hvac_device_info()

    _methodology = (
        "Rough estimate. Each AC-ramp nudge's kWh_avoided (kW-delta × capped "
        "30-min projection at nudge-eval time) valued at the TOU-effective "
        "rate captured at nudge-eval time. Forward-only: events logged before "
        "rate-capture contribute kWh but $0. NOT billing-grade; standalone "
        "family (NOT summed into energy_savings_total_*). See "
        "docs/TECH_DEBT.md."
    )


class HVACACRampSavingsTodaySensor(_ACRampSavingsSensorBase):
    """PLANNING_hvac_kwh_avoided_savings D2: AC-ramp $ saved since local midnight.

    Entity: sensor.ura_hvac_ac_ramp_savings_today
    """
    _attr_icon = "mdi:cash-plus"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_ramp_savings_today"
        self._attr_name = "76 · AC Ramp Savings Today"

    @property
    def native_value(self) -> float:
        cache = self._get_cache()
        if cache is None:
            return 0.0
        return round(float(cache.get("savings_today", 0.0)), 2)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "accuracy": "rough_estimate",
            "methodology": self._methodology,
        }


class HVACACRampSavingsBillingCycleSensor(_ACRampSavingsSensorBase):
    """PLANNING_hvac_kwh_avoided_savings D2: AC-ramp $ saved since billing-cycle start.

    Entity: sensor.ura_hvac_ac_ramp_savings_billing_cycle
    """
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_ramp_savings_billing_cycle"
        self._attr_name = "77 · AC Ramp Savings This Cycle"

    @property
    def native_value(self) -> float:
        cache = self._get_cache()
        if cache is None:
            return 0.0
        return round(float(cache.get("savings_cycle", 0.0)), 2)

    @property
    def extra_state_attributes(self) -> dict:
        cache = self._get_cache() or {}
        return {
            "accuracy": "rough_estimate",
            "methodology": self._methodology,
            # Review B L1: mirror the billing-cycle boundary provenance
            # from the sibling kWh sensor.
            "cycle_start_source": cache.get("cycle_start_source", "unknown"),
        }


class HVACACRampSavingsLifetimeSensor(_ACRampSavingsSensorBase):
    """PLANNING_hvac_kwh_avoided_savings D2: AC-ramp $ saved lifetime.

    Entity: sensor.ura_hvac_ac_ramp_savings_lifetime
    """
    _attr_icon = "mdi:cash-100"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_ramp_savings_lifetime"
        self._attr_name = "78 · AC Ramp Savings Lifetime"

    @property
    def native_value(self) -> float:
        cache = self._get_cache()
        if cache is None:
            return 0.0
        return round(float(cache.get("savings_lifetime", 0.0)), 2)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "accuracy": "rough_estimate",
            "methodology": self._methodology,
        }


class HVACACFalsePositiveRateSensor(
    _ACRampImpactSensorMixin, AggregationEntity, SensorEntity,
):
    """v4.5.12 D8: percentage of nudges where kWh rate did NOT drop
    after the action (rough effectiveness signal).

    **Manual force_nudge events are excluded** from the math (Risk R6
    from v4.5.11 plan) — testing-triggered nudges shouldn't pollute
    the metric.

    Returns `unavailable` until sample_size >= 5 (Risk R3 — small N
    is meaningless).

    Entity: sensor.ura_hvac_ac_false_positive_rate
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:chart-line-variant"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_ac_false_positive_rate"
        self._attr_name = "45 · AC Nudge False-Positive Rate"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self):
        cache = self._get_cache()
        if cache is None:
            return None  # → "unavailable" until coord ready
        rate = cache.get("false_positive_rate")
        # rate is None when sample_size < 5; HA renders as "unavailable"
        return rate

    @property
    def extra_state_attributes(self) -> dict:
        cache = self._get_cache()
        if cache is None:
            return {}
        return {
            "sample_size": cache.get("fp_sample_size", 0),
            "min_sample_for_display": 5,
            "excludes": "manual force_nudge events",
        }


class HVACZoneIntelligenceSensor(AggregationEntity, SensorEntity):
    """Zone intelligence summary sensor — count of away-override zones.

    v3.17.0 D7: House-level diagnostic showing zone intelligence activity.
    Entity: sensor.ura_hvac_coordinator_zone_intelligence
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-thermometer-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_coordinator_zone_intelligence"
        self._attr_name = "35 · HVAC Zone Intelligence"
        self._attr_device_info = _hvac_device_info()

    @property
    def native_value(self) -> int:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return 0
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return 0
        return sum(
            1 for z in hvac.zone_manager.zones.values()
            if z.zone_presence_state == "away"
        )

    @property
    def extra_state_attributes(self) -> dict:
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return {}
        zones = hvac.zone_manager.zones
        return {
            "zones_occupied": sum(
                1 for z in zones.values()
                if z.zone_presence_state == "occupied"
            ),
            "zones_away_override": [
                z.zone_id for z in zones.values()
                if z.zone_presence_state == "away"
            ],
            "zones_pre_arrival": [
                z.zone_id for z in zones.values()
                if z.zone_presence_state == "pre_arrival"
            ],
            # v5.7.1 fix-up (A1/B-3): rename to track unified pre-cool source
            # attr `_energy_precool_zones`. Old key `zones_solar_banking` is
            # retired (no compat alias per planning §10 Q4).
            "zones_energy_precool": list(
                getattr(hvac.predictor, "_energy_precool_zones", set())
            ),
            "zones_runtime_limited": [
                z.zone_id for z in zones.values()
                if z.zone_presence_state == "runtime_limited"
            ],
            "total_vacancy_sweeps_today": hvac.vacancy_sweeps_today,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_zi_update
            )
        )

    @callback
    def _handle_zi_update(self) -> None:
        self.async_schedule_update_ha_state()


class HVACPreArrivalDiagnosticSensor(AggregationEntity, SensorEntity):
    """Pre-arrival conditioning status and diagnostics.

    v3.18.6: Shows current pre-arrival state, active zones, trigger history.

    Entity: sensor.ura_hvac_pre_arrival_status
    Device: URA: HVAC Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-clock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_pre_arrival_status"
        self._attr_name = "40 · HVAC Pre-Arrival Status"
        self._attr_device_info = _hvac_device_info()

    def _get_hvac(self):
        """Get the HVAC coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("hvac")

    @property
    def native_value(self) -> str:
        hvac = self._get_hvac()
        if hvac is None:
            return "unavailable"
        if not hvac.pre_arrival_enabled:
            return "disabled"
        if getattr(hvac, '_pre_arrival_zones', None):
            return "active"
        return "idle"

    @property
    def extra_state_attributes(self) -> dict:
        hvac = self._get_hvac()
        if hvac is None:
            return {}
        predictor = getattr(hvac, '_predictor', None) or getattr(hvac, 'predictor', None)
        return {
            "enabled": hvac.pre_arrival_enabled,
            "sources": getattr(hvac, '_pre_arrival_sources', []),
            "active_zones": list(getattr(hvac, '_pre_arrival_zones', set())),
            "active_persons": dict(getattr(hvac, '_pre_arrival_persons', {})),
            "last_trigger_time": t.isoformat() if (t := getattr(hvac, '_last_pre_arrival_time', None)) else None,
            "last_trigger_source": getattr(hvac, '_last_pre_arrival_source', ""),
            "last_trigger_person": getattr(hvac, '_last_pre_arrival_person', ""),
            "triggers_today": getattr(hvac, '_pre_arrival_triggers_today', 0),
            "person_zone_map": getattr(hvac, '_person_zone_map', {}),
            "fan_rooms_activated": getattr(predictor, '_last_fan_activation_rooms', []) if predictor else [],
            "fan_rooms_skipped": getattr(predictor, '_last_fan_skipped_rooms', []) if predictor else [],
        }

    @property
    def available(self) -> bool:
        return self._get_hvac() is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_schedule_update_ha_state()


# ============================================================================
# v3.21.1 Cycle E: D2-D6 DIAGNOSTIC SENSORS
# ============================================================================


class HVACArresterStatusSensor(AggregationEntity, SensorEntity):
    """HVAC Override Arrester detailed status with per-zone breakdown.

    Entity: sensor.ura_hvac_arrester_status
    Device: URA: HVAC Coordinator

    Exposes the arrester state machine (monitoring/detected/grace/acting/cooldown)
    plus per-zone override tracking, compromise state, and AC reset status.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-lock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_hvac_arrester_status"
        self._attr_name = "30 · HVAC Arrester Status"
        self._attr_device_info = _hvac_device_info()

    def _get_arrester(self):
        """Get the OverrideArrester instance from HVAC coordinator."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return None
        return getattr(hvac, "override_arrester", None)

    @property
    def native_value(self) -> str:
        arrester = self._get_arrester()
        if arrester is None:
            return "not_initialized"
        # Map internal states to spec states
        state = arrester.get_arrester_state()
        state_map = {
            "idle": "monitoring",
            "grace_period": "grace",
            "compromise": "acting",
            "active": "detected",
            "disabled": "monitoring",
        }
        return state_map.get(state, state)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        arrester = self._get_arrester()
        if arrester is None:
            return {}

        detail = arrester.get_arrester_detail()
        zones = detail.get("zones", {})

        # Aggregate override/compromise counts from zones
        overrides_today = 0
        overrides_compromised_today = 0
        planned_action = None

        for zone_name, zone_detail in zones.items():
            overrides_today += zone_detail.get("overrides_today", 0)
            zone_state = zone_detail.get("state", "idle")
            if zone_state == "compromise":
                overrides_compromised_today += 1
                planned_action = "compromise"
            elif zone_state in ("override_active", "grace_period"):
                if zone_state == "grace_period":
                    planned_action = "revert"

        # AC reset status from arrester
        ac_reset_active = bool(getattr(arrester, "_reset_timers", {}))
        ac_reset_timeout_minutes = getattr(arrester, "_ac_reset_timeout", 0)

        attrs: dict[str, Any] = {
            "overrides_today": overrides_today,
            "overrides_compromised_today": overrides_compromised_today,
            "planned_action": planned_action,
            "ac_reset_active": ac_reset_active,
            "ac_reset_timeout_minutes": ac_reset_timeout_minutes,
            "enabled": detail.get("enabled", False),
            "ac_reset_enabled": detail.get("ac_reset_enabled", False),
            "energy_coast": detail.get("energy_coast", False),
            "zones": zones,
        }
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, self._handle_update_d2
            )
        )

    @callback
    def _handle_update_d2(self) -> None:
        self.async_schedule_update_ha_state()


class NMAlertStateSensor(AggregationEntity, SensorEntity):
    """Notification Manager alert state machine status.

    Entity: sensor.ura_nm_alert_state
    Device: URA: Notification Manager

    Exposes the NM alert lifecycle: idle -> alerting -> repeating -> cooldown.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-alert"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_nm_alert_state"
        self._attr_name = "NM Alert State"
        self._attr_device_info = _nm_device_info()

    @property
    def native_value(self) -> str:
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return "not_initialized"
        alert_state = getattr(nm, "_alert_state", None)
        if alert_state is None:
            return "idle"
        # AlertState is a StrEnum — .value gives the string
        return getattr(alert_state, "value", str(alert_state))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {}

        alert_data = getattr(nm, "_active_alert_data", None)
        attrs: dict[str, Any] = {
            "active_alert_severity": alert_data.get("severity") if isinstance(alert_data, dict) else None,
            "active_alert_hazard_type": alert_data.get("hazard_type") if isinstance(alert_data, dict) else None,
            "cooldown_remaining_seconds": getattr(nm, "_cooldown_remaining", 0),
            "repeat_timer_active": getattr(nm, "_repeat_unsub", None) is not None,
            "messaging_suppressed": getattr(nm, "_messaging_suppressed", False),
        }
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import (
            SIGNAL_NM_ENTITIES_UPDATE,
            SIGNAL_NM_ALERT_STATE_CHANGED,
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_NM_ENTITIES_UPDATE, self._handle_update_d3
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_NM_ALERT_STATE_CHANGED, self._handle_update_d3
            )
        )

    @callback
    def _handle_update_d3(self) -> None:
        self.async_schedule_update_ha_state()


class EnergyEnvoyStatusSensor(AggregationEntity, SensorEntity):
    """Envoy gateway availability status.

    Entity: sensor.ura_energy_envoy_status
    Device: URA: Energy Coordinator

    Tracks Envoy online/offline/stale state plus offline counts and last reading age.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:solar-panel"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_envoy_status"
        self._attr_name = "Envoy Status"
        self._attr_device_info = _energy_device_info()

    def _get_energy(self):
        """Get the Energy Coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("energy")

    @property
    def native_value(self) -> str:
        energy = self._get_energy()
        if energy is None:
            return "not_initialized"

        unavail_count = getattr(energy, "_envoy_unavailable_count", 0)
        last_available = getattr(energy, "_envoy_last_available", None)

        if unavail_count > 0:
            return "offline"

        # Review fix R1-F6: if never checked, return "initializing" not "online"
        if not last_available:
            return "initializing"

        # v4.3.0 D6: data-anomaly check (covers the v4.2.28 latent defect where
        # envoy reports state but values are zeroed/stale after reboot). If
        # cross-check fired within the last hour, surface as "stale" even
        # though the state objects themselves look fresh.
        anomaly_at = getattr(energy, "_envoy_data_anomaly_at", None)
        if anomaly_at:
            try:
                anomaly_ts = dt_util.parse_datetime(anomaly_at)
                if anomaly_ts is not None:
                    anomaly_age = (dt_util.now() - anomaly_ts).total_seconds()
                    if anomaly_age < 3600:  # last hour
                        return "stale"
            except (ValueError, TypeError):
                pass

        # v4.3.0 D6: freshness threshold tightened from a hardcoded 30 min
        # to (decision_interval_minutes × 2). With the default 5-min interval
        # that's 10 min — one missed cycle and the sensor flips, instead of
        # waiting 6 missed cycles.
        # v4.3.0 Review L22 fix: bound the threshold to [600s, 1800s] so a
        # pathological decision_interval=60 doesn't produce 120-min threshold
        # (worse than the old 30-min hardcode), and a decision_interval=1
        # doesn't make the sensor flap on every minor delay.
        try:
            last_ts = dt_util.parse_datetime(last_available)
            if last_ts is None:
                return "online"
            age = (dt_util.now() - last_ts).total_seconds()
            decision_interval_min = getattr(energy, "_decision_interval", 5)
            stale_threshold_seconds = max(
                600, min(1800, decision_interval_min * 60 * 2)
            )
            if age > stale_threshold_seconds:
                return "stale"
        except (ValueError, TypeError):
            pass

        return "online"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        energy = self._get_energy()
        if energy is None:
            return {}

        unavail_count = getattr(energy, "_envoy_unavailable_count", 0)
        last_available = getattr(energy, "_envoy_last_available", None)
        decision_interval = getattr(energy, "_decision_interval", 5)

        # Compute last reading age (review fix: use dt_util.parse_datetime)
        last_reading_age_seconds: float | None = None
        if last_available:
            try:
                last_ts = dt_util.parse_datetime(last_available)
                if last_ts is not None:
                    last_reading_age_seconds = round(
                        (dt_util.now() - last_ts).total_seconds(), 1
                    )
            except (ValueError, TypeError):
                pass

        # v4.3.0 D6: data-anomaly attributes
        anomaly_at = getattr(energy, "_envoy_data_anomaly_at", None)
        anomaly_age_seconds: float | None = None
        if anomaly_at:
            try:
                anomaly_ts = dt_util.parse_datetime(anomaly_at)
                if anomaly_ts is not None:
                    anomaly_age_seconds = round(
                        (dt_util.now() - anomaly_ts).total_seconds(), 1
                    )
            except (ValueError, TypeError):
                pass

        # EC Envoy boot-decoupling D7: degraded observability attrs.
        # `envoy_degraded` is True when the per-cycle envoy read is
        # unavailable; `envoy_degraded_since` carries the ISO timestamp
        # of the streak start (None when not degraded). Lets dashboards /
        # automations alert on persistent degrade without parsing the
        # native_value enum.
        envoy_degraded = bool(getattr(energy, "_envoy_degraded", False))
        envoy_degraded_since = getattr(
            energy, "_envoy_degraded_since", None
        )

        attrs: dict[str, Any] = {
            "offline_count_today": unavail_count,
            "last_reading_time": last_available,
            "last_reading_age_seconds": last_reading_age_seconds,
            "decision_interval_minutes": decision_interval,
            "stale_threshold_seconds": max(
                600, min(1800, decision_interval * 60 * 2)
            ),
            "data_anomaly_at": anomaly_at,
            "data_anomaly_age_seconds": anomaly_age_seconds,
            "envoy_degraded": envoy_degraded,
            "envoy_degraded_since": envoy_degraded_since,
        }
        return attrs

    async def async_added_to_hass(self) -> None:
        """Subscribe to energy entity update signal."""
        await super().async_added_to_hass()
        from .domain_coordinators.signals import SIGNAL_ENERGY_ENTITIES_UPDATE
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ENERGY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Refresh state when energy decision cycle completes."""
        self.async_schedule_update_ha_state()


class SafetyActiveCooldownsSensor(AggregationEntity, SensorEntity):
    """Safety alert deduplicator recent alerts.

    Entity: sensor.ura_safety_active_cooldowns
    Device: URA: Safety Coordinator

    Shows how many hazard types have fired within the maximum suppression
    window (3600s).  Actual per-severity windows are shorter (CRITICAL: 60s,
    HIGH: 300s, MEDIUM: 900s, LOW: 3600s) but the dedup cache keys do not
    include severity, so 3600s is used as an upper bound.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-sand"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_active_cooldowns"
        self._attr_name = "Safety Recent Alerts"
        self._attr_device_info = _safety_device_info()

    def _get_safety(self):
        """Get the Safety Coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("safety")

    @property
    def native_value(self) -> str:
        safety = self._get_safety()
        if safety is None:
            return "not_initialized"

        dedup = getattr(safety, "_deduplicator", None)
        if dedup is None:
            return "none"

        last_alerts = getattr(dedup, "_last_alert", {})
        if not last_alerts:
            return "none"

        # Count active cooldowns (within their suppression window)
        now = dt_util.utcnow()
        active_count = 0
        for key, last_time in last_alerts.items():
            # Keys are "hazard_type:location"
            # Use the maximum window (1 hour) as a generous bound for counting
            if isinstance(last_time, datetime):
                age = (now - last_time).total_seconds()
                if age < 3600:  # within max suppression window (1 hour)
                    active_count += 1

        if active_count == 0:
            return "none"
        return f"{active_count} recent"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        safety = self._get_safety()
        if safety is None:
            return {}

        dedup = getattr(safety, "_deduplicator", None)
        if dedup is None:
            return {}

        last_alerts = getattr(dedup, "_last_alert", {})
        if not last_alerts:
            return {"cooldowns": {}}

        now = dt_util.utcnow()
        cooldowns: dict[str, Any] = {}
        for key, last_time in last_alerts.items():
            if not isinstance(last_time, datetime):
                continue
            age = (now - last_time).total_seconds()
            # Report all entries within the maximum suppression window (upper bound;
            # actual window depends on severity: CRITICAL=60s, HIGH=300s, MEDIUM=900s, LOW=3600s)
            if age < 3600:
                remaining = max(0, 3600 - age)
                cooldowns[key] = {
                    "last_alert": last_time.isoformat(),
                    "age_seconds": round(age, 1),
                    "max_remaining_seconds": round(remaining, 1),
                }

        return {"cooldowns": cooldowns}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update_d5
            )
        )

    @callback
    def _handle_update_d5(self) -> None:
        self.async_schedule_update_ha_state()


class SecurityAuthorizedGuestsSensor(AggregationEntity, SensorEntity):
    """Security authorized guests and expected arrivals.

    Entity: sensor.ura_security_authorized_guests
    Device: URA: Security Coordinator

    Shows how many authorized guests / expected arrivals are active.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-check"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_security_authorized_guests"
        self._attr_name = "Security Authorized Guests"
        self._attr_device_info = _security_device_info()

    def _get_security(self):
        """Get the Security Coordinator instance."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        return manager.coordinators.get("security")

    @property
    def native_value(self) -> str:
        security = self._get_security()
        if security is None:
            return "not_initialized"

        checker = getattr(security, "_sanction_checker", None)
        if checker is None:
            return "none"

        guests = checker.get_authorized_guests_snapshot()
        arrivals = checker.get_expected_arrivals_snapshot()
        total = len(guests) + len(arrivals)

        if total == 0:
            return "none"
        return f"{total} guests"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        security = self._get_security()
        if security is None:
            return {}

        checker = getattr(security, "_sanction_checker", None)
        if checker is None:
            return {}

        guests = checker.get_authorized_guests_snapshot()
        arrivals = checker.get_expected_arrivals_snapshot()

        return {
            "guests": guests,
            "expected_arrivals": arrivals,
            "guest_count": len(guests),
            "arrival_count": len(arrivals),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update_d6
            )
        )

    @callback
    def _handle_update_d6(self) -> None:
        self.async_schedule_update_ha_state()


# ===========================================================================
# Activity Log sensor
# ===========================================================================

class URALastActivitySensor(AggregationEntity, SensorEntity):
    """Most recent URA activity with rolling buffer of recent actions.

    Entity: sensor.ura_last_activity
    Device: URA: Coordinator Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:history"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_last_activity"
        self._attr_name = "Last Activity"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )
        self._recent: list[dict] = []
        self._activities_today: int = 0
        self._notable_today: int = 0
        self._counter_date: str = ""  # YYYY-MM-DD for midnight reset
        self._last_description: str | None = None
        self._last_attrs: dict = {}

    async def async_added_to_hass(self) -> None:
        """Register signal listener and seed from DB."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_ACTIVITY_LOGGED
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ACTIVITY_LOGGED, self._handle_activity
            )
        )
        # Seed from DB
        try:
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database:
                rows = await database.get_recent_activities(limit=10)
                if rows:
                    self._recent = rows
                    self._last_description = rows[0].get("description")
                    self._last_attrs = {
                        "coordinator": rows[0].get("coordinator", ""),
                        "action": rows[0].get("action", ""),
                        "room": rows[0].get("room"),
                        "importance": rows[0].get("importance", "info"),
                        "timestamp": rows[0].get("timestamp", ""),
                    }
                    # Count today's activities from the seeded data
                    self._counter_date = dt_util.now().date().isoformat()
                    today_start = dt_util.start_of_local_day().isoformat()
                    for row in rows:
                        ts = row.get("timestamp", "")
                        if ts >= today_start:
                            self._activities_today += 1
                            if row.get("importance") in ("notable", "critical"):
                                self._notable_today += 1
        except Exception as exc:
            _LOGGER.debug("Activity sensor DB seed failed: %s", exc)

    @callback
    def _handle_activity(self, data: dict) -> None:
        """Handle SIGNAL_ACTIVITY_LOGGED."""
        self._last_description = data.get("description")
        self._last_attrs = {
            "coordinator": data.get("coordinator", ""),
            "action": data.get("action", ""),
            "room": data.get("room"),
            "importance": data.get("importance", "info"),
            "timestamp": data.get("timestamp", ""),
        }
        # Prepend to recent buffer, cap at 10
        self._recent.insert(0, data)
        if len(self._recent) > 10:
            self._recent = self._recent[:10]

        # Reset counters on day boundary
        today = dt_util.now().date().isoformat()
        if today != self._counter_date:
            self._activities_today = 0
            self._notable_today = 0
            self._counter_date = today

        self._activities_today += 1
        if data.get("importance") in ("notable", "critical"):
            self._notable_today += 1

        self.async_schedule_update_ha_state()

    @property
    def native_value(self) -> str | None:
        """Return description of most recent activity."""
        return self._last_description

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return activity details and rolling buffer."""
        attrs: dict[str, Any] = dict(self._last_attrs)

        # Time ago
        ts = self._last_attrs.get("timestamp")
        if ts:
            try:
                last_dt = dt_util.parse_datetime(ts)
                if last_dt is None:
                    last_dt = dt_util.utcnow()
                elif last_dt.tzinfo is None:
                    from datetime import timezone
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                delta = dt_util.utcnow() - last_dt
                minutes = int(delta.total_seconds() / 60)
                if minutes < 1:
                    attrs["time_ago"] = "just now"
                elif minutes < 60:
                    attrs["time_ago"] = f"{minutes}m ago"
                else:
                    attrs["time_ago"] = f"{minutes // 60}h {minutes % 60}m ago"
            except (ValueError, TypeError):
                attrs["time_ago"] = "unknown"

        # Recent activities (compact: description + timestamp only)
        attrs["recent_activities"] = [
            {
                "description": r.get("description", ""),
                "coordinator": r.get("coordinator", ""),
                "room": r.get("room"),
                "importance": r.get("importance", "info"),
                "timestamp": r.get("timestamp", ""),
            }
            for r in self._recent
        ]
        attrs["activities_today"] = self._activities_today
        attrs["notable_today"] = self._notable_today
        return attrs


# ============================================================================
# v4.0.0-B1: Bayesian Predictor Sensors (per-room, diagnostic)
# ============================================================================


class BayesianOccupancyPatternSensor(UniversalRoomEntity, SensorEntity):
    """Highest-probability time bin for room occupancy.

    Shows which time-of-day this room is most likely to be occupied.
    Diagnostic, disabled by default.
    """

    _attr_icon = "mdi:calendar-clock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize."""
        super().__init__(
            coordinator, "bayesian_occupancy_pattern",
            "Bayesian Occupancy Pattern",
        )

    @property
    def native_value(self) -> str | None:
        """Return the time bin name with highest occupancy."""
        predictor = self.hass.data.get(DOMAIN, {}).get("bayesian_predictor")
        if predictor is None:
            return None
        room_name = self.coordinator.entry.data.get("room_name", "")
        top = predictor.get_top_time_bin_for_room(room_name)
        if top is None:
            return "Learning"
        status = top.get("learning_status", "insufficient_data")
        if status == "insufficient_data":
            return "Learning"
        day_label = "Weekend" if top["day_type"] == 1 else "Weekday"
        return f"{top['time_bin_name']} ({day_label})"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return pattern details."""
        predictor = self.hass.data.get(DOMAIN, {}).get("bayesian_predictor")
        if predictor is None:
            return {}
        room_name = self.coordinator.entry.data.get("room_name", "")
        top = predictor.get_top_time_bin_for_room(room_name)
        if top is None:
            return {"room": room_name}
        return {
            "room": room_name,
            "time_bin": top.get("time_bin"),
            "time_bin_name": top.get("time_bin_name"),
            "day_type": top.get("day_type"),
            "probability": top.get("probability"),
            "learning_status": top.get("learning_status"),
        }


class BayesianDataQualitySensor(AggregationEntity, SensorEntity):
    """Bayesian predictor data quality summary.

    Entity: sensor.ura_bayesian_data_quality
    Device: URA: Coordinator Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:database-check"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_unique_id = f"{DOMAIN}_bayesian_data_quality"
        self._attr_name = "Bayesian Data Quality"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
        )

    @property
    def native_value(self) -> str | None:
        """Return summary state."""
        predictor = self.hass.data.get(DOMAIN, {}).get("bayesian_predictor")
        if predictor is None:
            return "not_initialized"
        report = predictor.quality_report
        if report is None:
            return "no_data"
        if report.total_rows == 0:
            return "no_data"
        pct = report.passed / report.total_rows * 100
        return f"{pct:.0f}% quality"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed quality metrics."""
        predictor = self.hass.data.get(DOMAIN, {}).get("bayesian_predictor")
        if predictor is None:
            return {}
        report = predictor.quality_report
        attrs: dict[str, Any] = {
            "belief_cells": predictor.belief_cell_count,
            "known_rooms": len(predictor.known_rooms),
            "known_persons": len(predictor.known_persons),
            "learning_suppressed": predictor.is_learning_suppressed,
        }
        if report:
            attrs.update({
                "total_rows": report.total_rows,
                "passed": report.passed,
                "null_rooms": report.null_rooms,
                "self_transitions": report.self_transitions,
                "impossible_durations": report.impossible_durations,
                "duplicate_timestamps": report.duplicate_timestamps,
                "unknown_rooms": report.unknown_rooms,
                "low_confidence": report.low_confidence,
                # v4.5.18: visibility metric — count of "same person +
                # same second + DIFFERENT (from, to)" rows (legitimate
                # multi-step path inside one PersonCoordinator cycle
                # that captured `now` once). Previously these were
                # over-counted in the `duplicate_timestamps` bucket,
                # inflating it and producing the misleading ~91%
                # data-quality reading. REPORTING-ONLY fix —
                # `_build_priors_from_transitions` never timestamp-
                # deduped, so Bayesian priors have ALWAYS included
                # these rows. Prediction quality unchanged.
                "same_second_distinct": report.same_second_distinct,
            })
        return attrs


# ============================================================================
# v4.0.0-B2: Prediction Sensors
# ============================================================================


class BayesianOccupancyForecastSensor(UniversalRoomEntity, SensorEntity):
    """Per-room Bayesian occupancy forecast (now / +1h / +4h).

    Shows current occupancy probability as the state value, with
    1-hour and 4-hour forecasts as attributes.
    Diagnostic, disabled by default.
    """

    _attr_icon = "mdi:crystal-ball"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize."""
        super().__init__(
            coordinator, "bayesian_occupancy_forecast",
            "Bayesian Occupancy Forecast",
        )

    @property
    def native_value(self) -> float | None:
        """Return current occupancy probability percentage."""
        predictor = self.hass.data.get(DOMAIN, {}).get("bayesian_predictor")
        if predictor is None:
            return None
        room_name = self.coordinator.entry.data.get("room_name", "")
        now = dt_util.now()
        prob = predictor.predict_room_occupancy_at_time(room_name, now)
        if prob is None:
            return None
        return round(prob * 100, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return forecast at now, +1h, +4h."""
        predictor = self.hass.data.get(DOMAIN, {}).get("bayesian_predictor")
        if predictor is None:
            return {}
        room_name = self.coordinator.entry.data.get("room_name", "")
        now = dt_util.now()
        attrs: dict[str, Any] = {"room": room_name}

        for label, delta in [("now", timedelta()), ("+1h", timedelta(hours=1)), ("+4h", timedelta(hours=4))]:
            future_dt = now + delta
            prob = predictor.predict_room_occupancy_at_time(room_name, future_dt)
            attrs[f"forecast_{label}"] = round(prob * 100, 1) if prob is not None else None

        # Include current learning status
        from .bayesian_predictor import _hour_to_time_bin, _day_type
        time_bin = _hour_to_time_bin(now.hour)
        day_type_val = _day_type(now)
        statuses = []
        for person_id in predictor.known_persons:
            pred = predictor.predict_room(person_id, time_bin, day_type_val)
            if pred:
                statuses.append(pred.get("learning_status", "insufficient_data"))
        _STATUS_ORDER = {"insufficient_data": 0, "learning": 1, "active": 2}
        attrs["learning_status"] = max(statuses, key=lambda s: _STATUS_ORDER.get(s, 0)) if statuses else "insufficient_data"

        return attrs


class BayesianPredictionAccuracySensor(AggregationEntity, SensorEntity):
    """Coordinator Manager sensor for Bayesian prediction accuracy.

    Shows Brier score as state, hit rate and total predictions as attributes.
    Enabled by default (not diagnostic-disabled).
    Entity: sensor.ura_bayesian_prediction_accuracy
    Device: URA: Coordinator Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:bullseye-arrow"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_bayesian_prediction_accuracy"
        self._attr_name = "Bayesian Prediction Accuracy"
        self._attr_device_info = _cm_device_info()
        self._cached_stats: dict = {
            "brier_score": None,
            "hit_rate": None,
            "total_predictions": 0,
        }
        self._last_query_time: float = 0

    async def async_update(self) -> None:
        """Fetch accuracy stats from Bayesian predictor (cached 30 min)."""
        import time
        now = time.monotonic()
        if now - self._last_query_time < 1800:  # 30 minutes
            return
        predictor = self.hass.data.get(DOMAIN, {}).get("bayesian_predictor")
        if predictor is None:
            return
        try:
            self._cached_stats = await predictor.get_accuracy_stats(days=7)
            self._last_query_time = now
        except Exception as e:
            _LOGGER.error("Error fetching Bayesian accuracy stats: %s", e)
            # v4.2.11: Update cache timer on exception to prevent log spam (review fix)
            self._last_query_time = now

    @property
    def native_value(self) -> float | None:
        """Return Brier score (lower = better, 0 = perfect)."""
        return self._cached_stats.get("brier_score")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed accuracy stats."""
        return {
            "brier_score": self._cached_stats.get("brier_score"),
            "hit_rate_pct": self._cached_stats.get("hit_rate"),
            "total_predictions_7d": self._cached_stats.get("total_predictions"),
            "window_days": 7,
        }

# v4.6.0: D4 — per-person next-room accuracy sensor


class PersonNextRoomAccuracySensor(AggregationEntity, SensorEntity):
    """Per-person next-room prediction accuracy sensor.

    Entity: sensor.ura_person_{person_id}_next_room_accuracy
    Device: URA: Coordinator Manager
    State: top-1 hit rate (7-day rolling, percent, 1 decimal).
    Returns None when no predictions exist to avoid a "0% accuracy" misread
    during the initial learning window.
    Refreshes on SIGNAL_NEXT_ROOM_PREDICTION_UPDATE (signal-driven, no polling).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:crosshairs-gps"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, person_id: str
    ) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._person_id = person_id
        self._attr_unique_id = (
            f"{DOMAIN}_person_{person_id.lower()}_next_room_accuracy"
        )
        self._attr_name = f"{person_id} Next Room Accuracy"
        self._attr_device_info = _cm_device_info()
        self._cached_stats: dict = {
            "top1_hit_rate": None,
            "top3_hit_rate": None,
            "brier_score": None,
            "predictions_7d": 0,
            "predictions_24h": 0,
            "most_recent_prediction_ts": None,
        }
        self._last_query_time: float = 0

    async def async_added_to_hass(self) -> None:
        """Subscribe to next-room prediction update signal."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NEXT_ROOM_PREDICTION_UPDATE

        # Bug Class #38: capture unsubscribe into async_on_remove so it fires
        # when the entity is removed, preventing a listener leak.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_NEXT_ROOM_PREDICTION_UPDATE,
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self, person_id: str) -> None:
        """Refresh only when the signal is for this person."""
        if person_id != self._person_id:
            return
        self.async_schedule_update_ha_state(force_refresh=True)

    async def async_update(self) -> None:
        """Query prediction_results for this person (cached 30 sec)."""
        import time
        import json

        now = time.monotonic()
        if now - self._last_query_time < 30:
            return

        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            return

        try:
            cutoff_7d = (
                dt_util.utcnow() - timedelta(days=7)
            ).strftime("%Y-%m-%d %H:%M:%S")
            cutoff_24h = (
                dt_util.utcnow() - timedelta(hours=24)
            ).strftime("%Y-%m-%d %H:%M:%S")

            import aiosqlite

            async with database._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """SELECT predicted_value, actual_value, error_value,
                              confidence, prediction_timestamp
                       FROM prediction_results
                       WHERE prediction_type = 'next_room'
                         AND person_id = ?
                         AND prediction_timestamp >= ?
                       ORDER BY prediction_timestamp DESC""",
                    (self._person_id, cutoff_7d),
                )
                rows = await cursor.fetchall()

                cursor24 = await db.execute(
                    """SELECT count(*) as cnt
                       FROM prediction_results
                       WHERE prediction_type = 'next_room'
                         AND person_id = ?
                         AND prediction_timestamp >= ?""",
                    (self._person_id, cutoff_24h),
                )
                row24 = await cursor24.fetchone()

            total = len(rows)
            if total == 0:
                self._cached_stats = {
                    "top1_hit_rate": None,
                    "top3_hit_rate": None,
                    "brier_score": None,
                    "predictions_7d": 0,
                    "predictions_24h": int(row24["cnt"]) if row24 else 0,
                    "most_recent_prediction_ts": None,
                }
                self._last_query_time = now
                return

            top1_hits = 0
            top3_hits = 0
            brier_sum = 0.0
            most_recent_ts = None

            for row in rows:
                actual = row["actual_value"]
                error_val = row["error_value"]

                # top-1: error_value encodes the Brier component; a hit is when
                # (1 - confidence)^2 < confidence^2, i.e. predicted_top == actual.
                # We reconstruct from predicted_value JSON which is authoritative.
                try:
                    pred_data = json.loads(row["predicted_value"])
                    predicted_top = pred_data.get("top")
                    alternatives = pred_data.get("alternatives", [])
                except (TypeError, ValueError):
                    pred_data = {}
                    predicted_top = None
                    alternatives = []

                is_top1_hit = predicted_top is not None and predicted_top == actual
                if is_top1_hit:
                    top1_hits += 1

                top3_rooms = {predicted_top} | set(alternatives)
                if actual in top3_rooms:
                    top3_hits += 1

                if error_val is not None:
                    brier_sum += float(error_val)

                if most_recent_ts is None and row["prediction_timestamp"]:
                    most_recent_ts = row["prediction_timestamp"]

            self._cached_stats = {
                "top1_hit_rate": round(top1_hits / total * 100, 1),
                "top3_hit_rate": round(top3_hits / total * 100, 1),
                "brier_score": round(brier_sum / total, 4),
                "predictions_7d": total,
                "predictions_24h": int(row24["cnt"]) if row24 else 0,
                "most_recent_prediction_ts": most_recent_ts,
            }
            _LOGGER.debug(
                "PersonNextRoomAccuracySensor %s: %d predictions, top1=%.1f%%",
                self._person_id,
                total,
                self._cached_stats["top1_hit_rate"],
            )
        except Exception as e:
            _LOGGER.error(
                "Error updating PersonNextRoomAccuracySensor for %s: %s",
                self._person_id, e,
            )
        finally:
            self._last_query_time = now

    @property
    def native_value(self) -> float | None:
        """Return top-1 hit rate as percent, or None when no data."""
        return self._cached_stats.get("top1_hit_rate")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return accuracy breakdown attributes."""
        return {
            "top3_hit_rate_pct": self._cached_stats.get("top3_hit_rate"),
            "brier_score": self._cached_stats.get("brier_score"),
            "predictions_7d": self._cached_stats.get("predictions_7d"),
            "predictions_24h": self._cached_stats.get("predictions_24h"),
            "most_recent_prediction_ts": self._cached_stats.get(
                "most_recent_prediction_ts"
            ),
        }


# v4.6.0: D5 — house-aggregate next-room accuracy sensor


class HouseNextRoomAccuracySensor(AggregationEntity, SensorEntity):
    """House-wide next-room prediction accuracy sensor.

    Entity: sensor.ura_coordinator_manager_house_next_room_accuracy
    Device: URA: Coordinator Manager
    State: aggregate top-1 hit rate across all persons (7-day rolling).
    Aggregate = sum(hits) / sum(predictions), NOT mean(per-person rates),
    to avoid small-n bias from a person with very few predictions.
    Refreshes on SIGNAL_NEXT_ROOM_PREDICTION_UPDATE for any person.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-analytics"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_house_next_room_accuracy"
        self._attr_name = "House Next Room Accuracy"
        self._attr_device_info = _cm_device_info()
        self._cached_stats: dict = {
            "top1_hit_rate": None,
            "per_person_accuracy": {},
            "total_predictions_7d": 0,
            "total_predictions_24h": 0,
            "brier_score": None,
            "oldest_prediction_ts": None,
        }
        self._last_query_time: float = 0

    async def async_added_to_hass(self) -> None:
        """Subscribe to next-room prediction update signal (all persons)."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NEXT_ROOM_PREDICTION_UPDATE

        # Bug Class #38: wrap with async_on_remove so unsubscribe fires on removal.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_NEXT_ROOM_PREDICTION_UPDATE,
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self, person_id: str) -> None:
        """Refresh on any person's score event — house sensor aggregates all."""
        self.async_schedule_update_ha_state(force_refresh=True)

    async def async_update(self) -> None:
        """Query prediction_results across all persons (cached 30 sec)."""
        import time
        import json

        now = time.monotonic()
        if now - self._last_query_time < 30:
            return

        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            return

        try:
            cutoff_7d = (
                dt_util.utcnow() - timedelta(days=7)
            ).strftime("%Y-%m-%d %H:%M:%S")
            cutoff_24h = (
                dt_util.utcnow() - timedelta(hours=24)
            ).strftime("%Y-%m-%d %H:%M:%S")

            import aiosqlite

            async with database._db_read() as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """SELECT person_id, predicted_value, actual_value,
                              error_value, prediction_timestamp
                       FROM prediction_results
                       WHERE prediction_type = 'next_room'
                         AND prediction_timestamp >= ?
                       ORDER BY prediction_timestamp ASC""",
                    (cutoff_7d,),
                )
                rows = await cursor.fetchall()

                cursor24 = await db.execute(
                    """SELECT count(*) as cnt
                       FROM prediction_results
                       WHERE prediction_type = 'next_room'
                         AND prediction_timestamp >= ?""",
                    (cutoff_24h,),
                )
                row24 = await cursor24.fetchone()

            total_hits = 0
            total_predictions = 0
            total_brier = 0.0
            person_hits: dict[str, int] = {}
            person_preds: dict[str, int] = {}
            oldest_ts: str | None = None

            for row in rows:
                pid = row["person_id"] or "unknown"
                actual = row["actual_value"]
                error_val = row["error_value"]

                try:
                    pred_data = json.loads(row["predicted_value"])
                    predicted_top = pred_data.get("top")
                except (TypeError, ValueError):
                    predicted_top = None

                is_hit = predicted_top is not None and predicted_top == actual

                person_preds[pid] = person_preds.get(pid, 0) + 1
                person_hits[pid] = person_hits.get(pid, 0) + (1 if is_hit else 0)
                total_predictions += 1
                if is_hit:
                    total_hits += 1
                if error_val is not None:
                    total_brier += float(error_val)

                if oldest_ts is None and row["prediction_timestamp"]:
                    oldest_ts = row["prediction_timestamp"]

            if total_predictions == 0:
                self._cached_stats = {
                    "top1_hit_rate": None,
                    "per_person_accuracy": {},
                    "total_predictions_7d": 0,
                    "total_predictions_24h": int(row24["cnt"]) if row24 else 0,
                    "brier_score": None,
                    "oldest_prediction_ts": None,
                }
                self._last_query_time = now
                return

            # Aggregate: sum(hits) / sum(predictions) — not mean of rates.
            per_person: dict[str, float | None] = {}
            for pid, n in person_preds.items():
                h = person_hits.get(pid, 0)
                per_person[pid] = round(h / n * 100, 1) if n > 0 else None

            self._cached_stats = {
                "top1_hit_rate": round(total_hits / total_predictions * 100, 1),
                "per_person_accuracy": per_person,
                "total_predictions_7d": total_predictions,
                "total_predictions_24h": int(row24["cnt"]) if row24 else 0,
                "brier_score": round(total_brier / total_predictions, 4),
                "oldest_prediction_ts": oldest_ts,
            }
            _LOGGER.info(
                "HouseNextRoomAccuracySensor: %d predictions, top1=%.1f%%",
                total_predictions,
                self._cached_stats["top1_hit_rate"],
            )
        except Exception as e:
            _LOGGER.error("Error updating HouseNextRoomAccuracySensor: %s", e)
        finally:
            self._last_query_time = now

    @property
    def native_value(self) -> float | None:
        """Return aggregate top-1 hit rate as percent, or None when no data."""
        return self._cached_stats.get("top1_hit_rate")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return house-wide accuracy breakdown."""
        return {
            "per_person_accuracy": self._cached_stats.get("per_person_accuracy"),
            "total_predictions_7d": self._cached_stats.get("total_predictions_7d"),
            "total_predictions_24h": self._cached_stats.get("total_predictions_24h"),
            "brier_score": self._cached_stats.get("brier_score"),
            "oldest_prediction_ts": self._cached_stats.get("oldest_prediction_ts"),
        }


# v4.6.2 D5 — per-person routine status sensor

# Mapping from worst unacknowledged severity integer to state string.
# v4.6.6: extended for 5-bucket AnomalySeverity (INFO=0/WARNING=1/ADVISORY=2/
# ALERT=3/CRITICAL=4). CRITICAL is now 4, not 2; the int 2 now means ADVISORY.
# Pre-v4.6.6 rows persisted with severity=2 (the old CRITICAL int) will be
# read back as ADVISORY → "shifted" — see PLANNING_v4.6.6_severity_refactor.md
# for the one-shot DB backfill that remaps the affected rows.
_SEVERITY_TO_ROUTINE_STATE: dict[int | None, str] = {
    None: "stable",       # no unacknowledged rows
    0: "drifting",        # AnomalySeverity.INFO
    1: "shifted",         # AnomalySeverity.WARNING
    2: "shifted",         # AnomalySeverity.ADVISORY (z 2-3)
    3: "shifted",         # AnomalySeverity.ALERT (z 3-4)
    4: "major_shift",     # AnomalySeverity.CRITICAL (z > 4)
}


class PersonRoutineStatusSensor(AggregationEntity, SensorEntity):
    """Per-person routine status sensor.

    Entity: sensor.ura_coordinator_manager_{person_id}_routine_status
    Device: URA: Coordinator Manager
    State: "stable" | "drifting" | "shifted" | "major_shift"

    Derives state from the worst-severity unacknowledged anomaly_log row
    for this person (coordinator_id='bayesian', type='bayesian.routine_shift',
    recovery_at IS NULL). Returns "stable" when zero rows; None (HA unknown)
    when the query itself fails.

    Refreshes on SIGNAL_ROUTINE_STATUS_UPDATE (signal-driven, no polling).
    30-second query cache prevents DB hammering when multiple signals fire.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-clock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, person_id: str
    ) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._person_id = person_id
        person_slug = person_id.lower().replace(" ", "_")
        self._attr_unique_id = f"{DOMAIN}_person_{person_slug}_routine_status"
        self._attr_name = f"{person_id} Routine Status"
        self._attr_device_info = _cm_device_info()
        self._cached_state: str | None = None
        self._cached_attrs: dict = {}
        self._last_query_time: float = 0

    async def async_added_to_hass(self) -> None:
        """Subscribe to routine status update signal (Bug Class #38)."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_ROUTINE_STATUS_UPDATE

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ROUTINE_STATUS_UPDATE,
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Schedule a state refresh — called on the event loop, no await here."""
        self.async_schedule_update_ha_state(force_refresh=True)

    async def async_update(self) -> None:
        """Query anomaly_log for unacknowledged routine shifts (cached 30 sec)."""
        import time

        now = time.monotonic()
        if now - self._last_query_time < 30:
            return

        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            return

        try:
            async with database._db_read() as db:
                cursor = await db.execute(
                    """SELECT severity, timestamp, context_json
                       FROM anomaly_log
                       WHERE coordinator_id = 'bayesian'
                         AND metric_name = 'bayesian.routine_shift'
                         AND person_id = ?
                         AND recovery_at IS NULL
                       ORDER BY timestamp DESC""",
                    (self._person_id,),
                )
                rows = await cursor.fetchall()

            if not rows:
                self._cached_state = "stable"
                self._cached_attrs = {
                    "unacknowledged_events": 0,
                    "max_magnitude": None,
                    "max_magnitude_cell": None,
                    "top_changes": [],
                    "last_check_at": dt_util.utcnow().isoformat(),
                }
                self._last_query_time = now
                return

            max_sev = max(int(r[0]) for r in rows)
            self._cached_state = _SEVERITY_TO_ROUTINE_STATE.get(max_sev, "shifted")

            # Build top_changes from the most severe rows (cap at 5)
            import json as _json
            top_changes = []
            for row in rows[:5]:
                try:
                    payload = _json.loads(row[2]) if row[2] else {}
                except (ValueError, TypeError):
                    payload = {}
                cell = payload.get("cell", {})
                top_changes.append({
                    "cell": cell,
                    "magnitude": payload.get("magnitude"),
                    "top_movers": payload.get("top_movers", []),
                })

            max_row_payload: dict = {}
            try:
                max_row_payload = _json.loads(rows[0][2]) if rows[0][2] else {}
            except (ValueError, TypeError):
                pass

            self._cached_attrs = {
                "unacknowledged_events": len(rows),
                "max_magnitude": max_row_payload.get("magnitude"),
                "max_magnitude_cell": max_row_payload.get("cell"),
                "top_changes": top_changes,
                "last_check_at": dt_util.utcnow().isoformat(),
            }
            _LOGGER.debug(
                "PersonRoutineStatusSensor %s: state=%s unack=%d",
                self._person_id,
                self._cached_state,
                len(rows),
            )
        except Exception as e:
            _LOGGER.warning(
                "PersonRoutineStatusSensor %s update failed: %s",
                self._person_id, e,
                exc_info=True,
            )
            # Leave cached_state as-is; will return None (unknown) if never set
        finally:
            self._last_query_time = now

    @property
    def native_value(self) -> str | None:
        """Return routine status string, or None (HA unknown) when query failed."""
        return self._cached_state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return anomaly detail attributes."""
        return self._cached_attrs


# v4.6.2 D5 — house-aggregate routine status sensor


class HouseRoutineStatusSensor(AggregationEntity, SensorEntity):
    """House-wide routine status sensor.

    Entity: sensor.ura_coordinator_manager_household_routine_status
    Device: URA: Coordinator Manager
    State: worst-case across all persons.

    Attributes include per-person breakdown and total unacknowledged events.
    Subscribes to SIGNAL_ROUTINE_STATUS_UPDATE (same as PersonRoutineStatusSensor).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:home-clock"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_household_routine_status"
        self._attr_name = "Household Routine Status"
        self._attr_device_info = _cm_device_info()
        self._cached_state: str | None = None
        self._cached_attrs: dict = {}
        self._last_query_time: float = 0

    async def async_added_to_hass(self) -> None:
        """Subscribe to routine status update signal (Bug Class #38)."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_ROUTINE_STATUS_UPDATE

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ROUTINE_STATUS_UPDATE,
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Schedule a state refresh."""
        self.async_schedule_update_ha_state(force_refresh=True)

    async def async_update(self) -> None:
        """Query anomaly_log grouped by person (cached 30 sec)."""
        import time

        now = time.monotonic()
        if now - self._last_query_time < 30:
            return

        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            return

        try:
            async with database._db_read() as db:
                cursor = await db.execute(
                    """SELECT person_id, MAX(severity) as max_sev, COUNT(*) as cnt
                       FROM anomaly_log
                       WHERE coordinator_id = 'bayesian'
                         AND metric_name = 'bayesian.routine_shift'
                         AND recovery_at IS NULL
                         AND person_id IS NOT NULL
                       GROUP BY person_id"""
                )
                rows = await cursor.fetchall()

            persons_stable: list[str] = []
            persons_drifting: list[str] = []
            persons_shifted: list[str] = []
            persons_major_shift: list[str] = []
            total_unack = 0

            for row in rows:
                pid, max_sev, cnt = row[0], int(row[1]), int(row[2])
                total_unack += cnt
                state = _SEVERITY_TO_ROUTINE_STATE.get(max_sev, "shifted")
                if state == "stable":
                    persons_stable.append(pid)
                elif state == "drifting":
                    persons_drifting.append(pid)
                elif state == "shifted":
                    persons_shifted.append(pid)
                else:
                    persons_major_shift.append(pid)

            if not rows:
                self._cached_state = "stable"
            elif persons_major_shift:
                self._cached_state = "major_shift"
            elif persons_shifted:
                self._cached_state = "shifted"
            elif persons_drifting:
                self._cached_state = "drifting"
            else:
                self._cached_state = "stable"

            self._cached_attrs = {
                "persons_stable": persons_stable,
                "persons_drifting": persons_drifting,
                "persons_shifted": persons_shifted,
                "persons_major_shift": persons_major_shift,
                "total_unacknowledged_events": total_unack,
            }
            _LOGGER.debug(
                "HouseRoutineStatusSensor: state=%s total_unack=%d",
                self._cached_state,
                total_unack,
            )
        except Exception as e:
            _LOGGER.warning(
                "HouseRoutineStatusSensor update failed: %s", e, exc_info=True
            )
        finally:
            self._last_query_time = now

    @property
    def native_value(self) -> str | None:
        """Return worst-case house routine status."""
        return self._cached_state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return per-person breakdown."""
        return self._cached_attrs


class OccupancyPercentageTodaySensor(UniversalRoomEntity, SensorEntity):
    """Percentage of today the room has been occupied.

    Diagnostic, disabled by default.
    """

    _attr_icon = "mdi:percent-circle"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize."""
        super().__init__(
            coordinator, "occupancy_pct_today",
            "Occupancy Pct Today",
        )
        self._cached_value: float | None = None

    async def async_update(self) -> None:
        """Calculate occupancy percentage for today."""
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            self._cached_value = None
            return
        room_name = self.coordinator.entry.data.get("room_name", "")
        if not room_name:
            self._cached_value = None
            return
        try:
            occupied_secs = await database.get_occupancy_time_today(room_name)
            now = dt_util.now()
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elapsed_secs = (now - midnight).total_seconds()
            if elapsed_secs > 0:
                self._cached_value = round(
                    occupied_secs / elapsed_secs * 100, 1
                )
            else:
                self._cached_value = 0.0
        except Exception as e:
            _LOGGER.error("Error calculating occupancy pct: %s", e)
            self._cached_value = None

    @property
    def native_value(self) -> float | None:
        """Return occupancy percentage."""
        return self._cached_value


class TimeOccupiedTodaySensor(UniversalRoomEntity, SensorEntity):
    """Total time the room has been occupied today (minutes).

    Diagnostic, disabled by default.
    """

    _attr_icon = "mdi:timer-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize."""
        super().__init__(
            coordinator, "time_occupied_today",
            "Time Occupied Today",
        )
        self._cached_value: int | None = None

    async def async_update(self) -> None:
        """Fetch occupied time from DB."""
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            self._cached_value = None
            return
        room_name = self.coordinator.entry.data.get("room_name", "")
        if not room_name:
            self._cached_value = None
            return
        try:
            occupied_secs = await database.get_occupancy_time_today(room_name)
            self._cached_value = occupied_secs // 60
        except Exception as e:
            _LOGGER.error("Error fetching time occupied: %s", e)
            self._cached_value = None

    @property
    def native_value(self) -> int | None:
        """Return occupied minutes."""
        return self._cached_value


class TimeUncomfortableTodaySensor(UniversalRoomEntity, SensorEntity):
    """Minutes outside comfort zone while occupied today.

    Diagnostic, disabled by default.
    """

    _attr_icon = "mdi:thermometer-alert"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize."""
        super().__init__(
            coordinator, "time_uncomfortable_today",
            "Time Uncomfortable Today",
        )
        self._cached_value: int | None = None

    async def async_update(self) -> None:
        """Fetch uncomfortable minutes from DB."""
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            self._cached_value = None
            return
        room_name = self.coordinator.entry.data.get("room_name", "")
        if not room_name:
            self._cached_value = None
            return
        try:
            self._cached_value = await database.get_uncomfortable_minutes_today(
                room_name
            )
        except Exception as e:
            _LOGGER.error("Error fetching uncomfortable minutes: %s", e)
            self._cached_value = None

    @property
    def native_value(self) -> int | None:
        """Return uncomfortable minutes."""
        return self._cached_value


class AvgTimeToComfortSensor(UniversalRoomEntity, SensorEntity):
    """Average time to reach comfort after occupancy starts (minutes).

    Estimated from the ratio of uncomfortable-to-total occupied time.
    If uncomfort is low, the room reaches comfort quickly.
    Diagnostic, disabled by default.
    """

    _attr_icon = "mdi:clock-fast"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize."""
        super().__init__(
            coordinator, "avg_time_to_comfort",
            "Avg Time to Comfort",
        )
        self._cached_value: int | None = None

    async def async_update(self) -> None:
        """Estimate avg time to comfort from today's data."""
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            self._cached_value = None
            return
        room_name = self.coordinator.entry.data.get("room_name", "")
        if not room_name:
            self._cached_value = None
            return
        try:
            occupied_secs = await database.get_occupancy_time_today(room_name)
            uncomfortable_mins = await database.get_uncomfortable_minutes_today(
                room_name
            )
            occupied_mins = occupied_secs // 60
            if occupied_mins > 0:
                # Ratio of uncomfortable time gives average ramp-up
                # If 10% of occupied time is uncomfortable, avg comfort
                # arrival is ~that fraction of average session length
                uncomfort_ratio = uncomfortable_mins / occupied_mins
                # Average session is ~30 min; comfort time scales with ratio
                self._cached_value = max(0, round(uncomfort_ratio * 30))
            else:
                self._cached_value = None
        except Exception as e:
            _LOGGER.error("Error estimating time to comfort: %s", e)
            self._cached_value = None

    @property
    def native_value(self) -> int | None:
        """Return estimated minutes to comfort."""
        return self._cached_value


# =========================================================================
# v4.2.10: URA Memory Diagnostic Sensors
# =========================================================================


def _cm_device_info():
    """Device info for Coordinator Manager sensors."""
    from homeassistant.helpers.device_registry import DeviceInfo
    from .const import VERSION
    return DeviceInfo(
        identifiers={(DOMAIN, "coordinator_manager")},
        name="URA: Coordinator Manager",
        manufacturer="Universal Room Automation",
        model="Coordinator Manager",
        sw_version=VERSION,
    )


class URAMemoryUsageSensor(AggregationEntity, SensorEntity):
    """URA total in-memory footprint.

    Entity: sensor.ura_coordinator_manager_memory_usage
    Device: URA: Coordinator Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:memory"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "items"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_memory_usage"
        self._attr_name = "Memory Usage"
        self._attr_device_info = _cm_device_info()
        # v4.2.11: Cache _count_items result so native_value and
        # extra_state_attributes return consistent data (review fix)
        self._cached_total: int = 0
        self._cached_attrs: dict[str, Any] = {}

    def _count_items(self) -> tuple[int, dict[str, Any]]:
        """Count items in known-growable URA structures."""
        ura_data = self.hass.data.get(DOMAIN)
        if not ura_data:
            return 0, {}
        attrs: dict[str, Any] = {}
        total = 0

        # Top-level keys
        attrs["hass_data_keys"] = len(ura_data)
        total += len(ura_data)

        # DB stats
        db = ura_data.get("database")
        if db and hasattr(db, "_db_stats"):
            attrs["db_writes_total"] = db._db_stats.get("writes", 0)
            attrs["db_queue_peak"] = db._db_stats.get("queue_peak", 0)
            attrs["db_queue_current"] = db._write_queue.qsize() if hasattr(db, "_write_queue") else 0
            total += attrs["db_queue_current"]

        # Activity logger dedup cache
        al = ura_data.get("activity_logger")
        if al and hasattr(al, "_dedup_cache"):
            count = len(al._dedup_cache)
            attrs["activity_dedup_cache"] = count
            total += count

        # Bayesian beliefs
        bp = ura_data.get("bayesian_predictor")
        if bp and hasattr(bp, "_beliefs"):
            count = len(bp._beliefs) if bp._beliefs else 0
            attrs["bayesian_belief_cells"] = count
            total += count

        # Coordinator count
        cm = ura_data.get("coordinator_manager")
        if cm and hasattr(cm, "coordinators"):
            attrs["coordinators"] = len(cm.coordinators)

        # Process RSS (whole HA process — for correlation)
        try:
            import resource
            rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # macOS returns bytes, Linux returns KB
            import sys as _sys
            if _sys.platform == "darwin":
                rss_kb = rss_kb // 1024
            attrs["process_rss_kb"] = rss_kb
        except Exception:
            pass

        return total, attrs

    async def async_update(self) -> None:
        """Cache _count_items so properties return consistent snapshot."""
        self._cached_total, self._cached_attrs = self._count_items()

    @property
    def native_value(self) -> int | None:
        return self._cached_total

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._cached_attrs


class URAMemoryDeltaSensor(AggregationEntity, SensorEntity):
    """Process RSS memory change since last measurement (MB).

    Tracks the entire HA process memory via resource.getrusage.
    Positive = growing, negative = shrinking, zero = stable.
    If consistently positive, something is leaking.

    Entity: sensor.ura_coordinator_manager_memory_delta
    Device: URA: Coordinator Manager
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:delta"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "MB"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_memory_delta"
        self._attr_name = "Memory Delta"
        self._attr_device_info = _cm_device_info()
        self._prev_rss_mb: float | None = None
        self._cached_delta: float = 0.0

    def _get_rss_mb(self) -> float:
        """Get process RSS in MB."""
        try:
            import resource
            import sys as _sys
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if _sys.platform == "darwin":
                return rss / (1024 * 1024)  # bytes → MB
            return rss / 1024  # KB → MB
        except Exception:
            return 0.0

    async def async_update(self) -> None:
        """Compute RSS delta once per poll — property is side-effect free."""
        current = round(self._get_rss_mb(), 1)
        if self._prev_rss_mb is None:
            self._prev_rss_mb = current
            self._cached_delta = 0.0
        else:
            self._cached_delta = round(current - self._prev_rss_mb, 1)
            self._prev_rss_mb = current

    @property
    def native_value(self) -> float | None:
        return self._cached_delta


# =============================================================================
# v4.6.3 D12 — sensor.ura_coordinator_manager_recent_anomalies
# =============================================================================


class URARecentAnomaliesSensor(AggregationEntity, SensorEntity):
    """House-level count of anomalies in the last 24 h across all coordinators.

    Entity: sensor.ura_coordinator_manager_recent_anomalies
    Device: URA: Coordinator Manager

    Refreshes on SIGNAL_ACTIVITY_LOGGED so it picks up new anomaly emits
    immediately when ActivityLogger fires (D12 integration).  Queries the
    anomaly_log table using idx_anomaly_timestamp index.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "anomalies"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_recent_anomalies"
        self._attr_name = "Recent Anomalies"
        self._attr_device_info = _cm_device_info()
        self._count_24h: int = 0
        self._top_10: list = []
        self._by_coordinator: dict = {}
        self._by_severity: dict = {}
        self._by_type: dict = {}
        self._unsub: object = None
        # A3 fix: in-flight guard to prevent concurrent refresh tasks on burst
        # of anomaly signals.  If a refresh is already running and another
        # dispatch arrives, we set _refresh_pending=True so the running refresh
        # will re-run once it completes instead of spawning a parallel task.
        self._refresh_in_flight: bool = False
        self._refresh_pending: bool = False
        # v4.6.5.3 M2: handle for the one-shot SIGNAL_DATABASE_READY
        # subscription. Set when the DB isn't yet available at
        # async_added_to_hass time; cleared after first fire (signal only
        # fires once per setup) or on entity teardown. Replaces v4.6.5.2's
        # _initial_load_task polling helper — event-driven, no sleep loop.
        self._unsub_db_ready: object = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Subscribe to SIGNAL_ACTIVITY_LOGGED to refresh when anomalies arrive.
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import (
            SIGNAL_ACTIVITY_LOGGED,
            SIGNAL_DATABASE_READY,
        )

        def _handle_activity_logged(payload: dict) -> None:
            # Only refresh if the logged action is "anomaly" so normal activity
            # events don't trigger an expensive DB query every cycle.
            # A3 fix: in-flight guard prevents burst of concurrent refresh tasks.
            # If a refresh is already running, set pending so it re-runs once done.
            #
            # v4.6.3.2 fix: SIGNAL_ACTIVITY_LOGGED fires on whichever thread
            # invoked async_dispatcher_send (event loop OR sync worker). Use
            # hass.add_job (thread-safe) instead of async_create_task — the
            # latter raises RuntimeError when called from a non-event-loop
            # thread under ReportBehavior.ERROR for custom integrations.
            # Observed in v4.6.3.1 wedge: 3× dispatcher exceptions blocked
            # sensor refresh and orphaned coroutines (which then surfaced
            # via "coroutine never awaited" warnings at random GC sites).
            if payload.get("action") == "anomaly":
                if self._refresh_in_flight:
                    self._refresh_pending = True
                else:
                    self.hass.add_job(self._async_refresh())

        self._unsub = async_dispatcher_connect(
            self.hass, SIGNAL_ACTIVITY_LOGGED, _handle_activity_logged
        )
        self.async_on_remove(lambda: self._unsub() if self._unsub else None)

        # v4.6.5.3 M2: event-driven initial load (replaces v4.6.5.2's 30s polling).
        # If the database is already in hass.data, run the initial refresh now.
        # Otherwise, subscribe to SIGNAL_DATABASE_READY and refresh once it
        # fires — dispatched from __init__.py the moment the DB is assigned.
        # The CM entry's sensor add can race against the room entry's DB init;
        # this signal closes the race deterministically without polling.
        if self.hass.data.get(DOMAIN, {}).get("database") is not None:
            await self._async_refresh()
        else:
            def _handle_db_ready(*_args, **_kwargs) -> None:
                # Fire-and-forget: signal handlers can't be async, schedule
                # the refresh via hass.add_job (thread-safe per v4.6.3.2 lesson).
                self.hass.add_job(self._async_refresh())
                # Auto-unsubscribe — SIGNAL_DATABASE_READY only fires once
                # per setup, but defensive unsub avoids redundant refreshes
                # if URA is reloaded.
                if self._unsub_db_ready is not None:
                    self._unsub_db_ready()
                    self._unsub_db_ready = None

            self._unsub_db_ready = async_dispatcher_connect(
                self.hass, SIGNAL_DATABASE_READY, _handle_db_ready
            )
            self.async_on_remove(
                lambda: self._unsub_db_ready()
                if self._unsub_db_ready is not None else None
            )

    async def _async_refresh(self) -> None:
        """Query anomaly_log for last 24 h using idx_anomaly_timestamp index.

        A3 fix: protected by an in-flight guard.  If called while a refresh is
        already running (from a signal burst), the second call sets
        _refresh_pending and returns immediately.  When the running refresh
        finishes it checks _refresh_pending and re-runs once, ensuring at
        most one queued follow-up regardless of burst size.
        """
        if self._refresh_in_flight:
            self._refresh_pending = True
            return
        self._refresh_in_flight = True
        try:
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database is None:
                return

            from datetime import timedelta
            cutoff = (dt_util.utcnow() - timedelta(hours=24)).isoformat()

            async with database._db_read() as db:
                # COUNT query — uses idx_anomaly_timestamp via WHERE timestamp >=
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM anomaly_log WHERE timestamp >= ?",
                    (cutoff,),
                )
                row = await cursor.fetchone()
                self._count_24h = row[0] if row else 0

                # Top-10 most recent
                cursor = await db.execute(
                    """SELECT timestamp, coordinator_id, severity, metric_name
                       FROM anomaly_log
                       WHERE timestamp >= ?
                       ORDER BY timestamp DESC
                       LIMIT 10""",
                    (cutoff,),
                )
                rows = await cursor.fetchall()
                self._top_10 = [
                    {
                        "timestamp": r[0],
                        "coordinator": r[1],
                        "severity": r[2],
                        "metric": r[3],  # C8 fix: renamed from "type" to "metric"
                    }
                    for r in rows
                ]

                # By coordinator
                cursor = await db.execute(
                    """SELECT coordinator_id, COUNT(*) as n
                       FROM anomaly_log
                       WHERE timestamp >= ?
                       GROUP BY coordinator_id""",
                    (cutoff,),
                )
                self._by_coordinator = {r[0]: r[1] for r in await cursor.fetchall()}

                # By severity
                cursor = await db.execute(
                    """SELECT severity, COUNT(*) as n
                       FROM anomaly_log
                       WHERE timestamp >= ?
                       GROUP BY severity""",
                    (cutoff,),
                )
                self._by_severity = {str(r[0]): r[1] for r in await cursor.fetchall()}

                # By anomaly_type (type bucket).
                # v4.7.12 fix-up (Review A A3 + Review C C-M3 convergent):
                # widened COALESCE to read anomaly_type first, falling back
                # to event_class for legacy rows. When v5.0 drops the
                # event_class column this reader still works.
                cursor = await db.execute(
                    """SELECT COALESCE(anomaly_type, event_class, 'point_in_time'), COUNT(*) as n
                       FROM anomaly_log
                       WHERE timestamp >= ?
                       GROUP BY COALESCE(anomaly_type, event_class, 'point_in_time')""",
                    (cutoff,),
                )
                self._by_type = {r[0]: r[1] for r in await cursor.fetchall()}

            self.async_write_ha_state()
        except Exception:
            _LOGGER.debug("RecentAnomaliesSensor refresh failed", exc_info=True)
        finally:
            self._refresh_in_flight = False
            # If a dispatch arrived while we were running, do one follow-up refresh
            if self._refresh_pending:
                self._refresh_pending = False
                self.hass.async_create_task(self._async_refresh())

    @property
    def native_value(self) -> int:
        return self._count_24h

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "top_10": self._top_10,
            "by_coordinator": self._by_coordinator,
            "by_severity": self._by_severity,
            "by_type": self._by_type,
            "window_hours": 24,
        }


class URASetupDurationSensor(AggregationEntity, SensorEntity):
    """Diagnostic sensor: URA async_setup_entry duration (last boot).

    Entity: sensor.ura_setup_duration_seconds
    Device: URA: Coordinator Manager

    v4.6.10 D2: Surfaces the boot-time telemetry captured in D1 so HA's
    history graph shows setup duration trend across reboots.
    Reads from hass.data[DOMAIN]["setup_telemetry"] — populated by
    __init__.py immediately after coordinator_manager.async_start() returns.
    """

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "s"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True
    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_setup_duration_seconds"
        self._attr_name = "URA Setup Duration"
        # D2: Override AggregationEntity's default (DOMAIN, "integration") device
        # to attach to the CM device — confirmed by reading AggregationEntity.__init__
        # which sets identifiers={(DOMAIN, "integration")}. CM sensors use _cm_device_info().
        self._attr_device_info = _cm_device_info()

    @property
    def native_value(self) -> float | None:
        """Return last boot setup duration in seconds, or None if not yet captured.

        Review fix A-M2: return None (not 0.0) when duration_seconds key is missing.
        Honors the "None when unknown" contract for HA sensor semantics.
        """
        try:
            telem = self.hass.data.get(DOMAIN, {}).get("setup_telemetry")
            if not telem:
                return None
            dur = telem.get("duration_seconds")
            if dur is None:
                return None
            return round(float(dur), 3)
        except Exception:
            _LOGGER.debug("URASetupDurationSensor: native_value read failed", exc_info=True)
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return timing breakdown and counts from last boot."""
        try:
            telem = self.hass.data.get(DOMAIN, {}).get("setup_telemetry") or {}
            return {
                "started_at": telem.get("started"),
                "completed_at": telem.get("completed"),
                "coordinator_count": telem.get("coordinator_count"),
                "room_count": telem.get("room_count"),
            }
        except Exception:
            _LOGGER.debug("URASetupDurationSensor: extra_state_attributes read failed", exc_info=True)
            return {}


# ============================================================================
# v4.6.11 D4.8 — Safety Events Summary Sensor
# ============================================================================


class SafetyEventsSummarySensor(AggregationEntity, SensorEntity):
    """Safety events in last 24h from ura_activity_log.

    Entity: sensor.ura_safety_events_summary
    Device: URA: Safety Coordinator
    State: events_today_count (int)
    Attributes: auto_dismissed_count, last_event_at, window_hours

    Bug Class #26: 60s in-sensor cache before re-query.
    Bug Class #36: cache cleared on entity remove (async_will_remove_from_hass).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    _CACHE_TTL_S = 60

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_events_summary"
        self._attr_name = "Safety Events Summary"
        self._attr_device_info = _safety_device_info()
        self._cache_time: datetime | None = None
        self._cached_count: int = 0
        self._cached_auto_dismissed: int = 0
        self._cached_last_event_at: str | None = None
        self._refresh_task: asyncio.Task | None = None

    async def _refresh_cache(self) -> None:
        """Query ura_activity_log for last 24h safety events."""
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is None:
            return
        cutoff = (dt_util.utcnow() - timedelta(hours=24)).isoformat()
        try:
            # Review A H1 / Review C H3: SELECT must go through the read-only
            # connection — _db() is the serialized write queue. Using it here
            # would block real writes (save_baselines, save_anomaly_event)
            # behind a 60s-cadence read.
            async with db._db_read() as conn:
                cursor = await conn.execute(
                    """SELECT COUNT(*),
                              SUM(CASE WHEN action LIKE '%dismiss%'
                                        OR action LIKE '%auto_clear%'
                                   THEN 1 ELSE 0 END),
                              MAX(timestamp)
                       FROM ura_activity_log
                       WHERE coordinator='safety' AND timestamp >= ?""",
                    (cutoff,),
                )
                row = await cursor.fetchone()
                if row:
                    self._cached_count = int(row[0] or 0)
                    self._cached_auto_dismissed = int(row[1] or 0)
                    self._cached_last_event_at = row[2]
                self._cache_time = dt_util.utcnow()
        except Exception:
            _LOGGER.debug(
                "SafetyEventsSummarySensor: query failed (non-fatal)", exc_info=True
            )

    def _cache_stale(self) -> bool:
        """Return True if cache is older than TTL or not yet populated."""
        if self._cache_time is None:
            return True
        age = (dt_util.utcnow() - self._cache_time).total_seconds()
        return age >= self._CACHE_TTL_S

    @property
    def native_value(self) -> int:
        """Return count of safety events in last 24h."""
        if self._cache_stale() and (
            self._refresh_task is None or self._refresh_task.done()
        ):
            # Review C C2: track + guard against re-entry so we don't pile up
            # overlapping queries when the property is hot. The task is
            # cancelled in async_will_remove_from_hass (Bug Class #19).
            self._refresh_task = self.hass.async_create_task(self._refresh_cache())
        return self._cached_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return breakdown attributes."""
        return {
            "auto_dismissed_count": self._cached_auto_dismissed,
            "last_event_at": self._cached_last_event_at,
            "window_hours": 24,
        }

    async def async_will_remove_from_hass(self) -> None:
        """Clear cache + cancel in-flight refresh (Bug Classes #19, #36, #38)."""
        # Review C C1: super() cleans up AggregationEntity._agg_retry_unsub.
        await super().async_will_remove_from_hass()
        if self._refresh_task is not None and not self._refresh_task.done():
            self._refresh_task.cancel()
        self._refresh_task = None
        self._cache_time = None
        self._cached_count = 0
        self._cached_auto_dismissed = 0
        self._cached_last_event_at = None


# ============================================================================
# v4.6.9 D5: Safety Coordinator — Recent Events Aggregator
# ============================================================================


class SafetyRecentEventsSensor(AggregationEntity, SensorEntity):
    """Safety Coordinator recent-events ring buffer sensor.

    Entity: sensor.ura_safety_coordinator_recent_events
    Device: URA: Safety Coordinator
    State: int — count of events in the last 24h (never '—'/None/unknown)

    v4.6.9 D5: Exposes the in-memory event ring buffer from SafetyCoordinator
    as a PWA-consumable sensor. State is always int (0 when buffer empty).

    Bug-class guards:
      #11  — all timestamps are UTC ISO 8601 strings (dt_util.utcnow().isoformat())
      #22  — severity uses EventSeverity StrEnum (info|advisory|alert|critical)
      #25  — buffer is deque(maxlen=20); hard cap enforced in coordinator
      #29  — empty-buffer branch returns 0 + empty list (not null/unknown)
      #37  — extra_state_attributes has stable shape: events, last_event_at_iso,
              severity_breakdown always present regardless of buffer state
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert"
    # Tier 2-DB Reviewer C M1: state is a sliding-window count from a volatile
    # in-memory ring buffer (resets on HA restart). HA long-term statistics
    # would record a discontinuous time series for it. state_class=None opts
    # out of LTS recording.

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_recent_events"
        self._attr_name = "Recent Events"
        self._attr_device_info = _safety_device_info()

    def _get_events_data(self) -> dict | None:
        """Fetch recent-events data from SafetyCoordinator.

        Returns None when the coordinator is unavailable; callers fall back
        gracefully to the empty-buffer shape.
        """
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return None
            safety = manager.coordinators.get("safety")
            if safety is None:
                return None
            return safety.get_recent_events()
        except Exception:
            _LOGGER.debug(
                "SafetyRecentEventsSensor: get_recent_events() failed",
                exc_info=True,
            )
            return None

    @property
    def native_value(self) -> int:
        """Return number of events in the last 24h.

        Bug Class #29: always returns int 0 on empty buffer — never None/unknown.
        """
        data = self._get_events_data()
        if data is None:
            return 0
        return int(data.get("count_24h", 0))

    @property
    def extra_state_attributes(self) -> dict:
        """Return flat events list, last_event_at_iso, and severity_breakdown.

        Bug Class #37: all three keys are always present regardless of buffer state.
        Bug Class #25: events list capped at 20 entries (enforced by deque in coordinator).
        """
        data = self._get_events_data()
        if data is None:
            return {
                "events": [],
                "last_event_at_iso": None,
                "severity_breakdown": {
                    "info": 0,
                    "advisory": 0,
                    "alert": 0,
                    "critical": 0,
                },
            }
        return {
            "events": data.get("events", []),
            "last_event_at_iso": data.get("last_event_at_iso"),
            "severity_breakdown": data.get(
                "severity_breakdown",
                {"info": 0, "advisory": 0, "alert": 0, "critical": 0},
            ),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to safety entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle safety entity update signal."""
        self.async_schedule_update_ha_state()


# ============================================================================
# v4.6.13 — Coordinator Telemetry Sensor Set (Dashboard Cycle C)
# ============================================================================
#
# Five deliverables surfacing per-coordinator decision telemetry to the v5
# Diagnostics tab. All sensors read existing tables (no schema changes):
#   D1 — decisions_today per UI coordinator (5 sensors)
#   D2 — override_frequency per UI coordinator (5 sensors)
#   D3 — compliance_rate per UI coordinator (5 sensors)
#   D4 — DB size in MB (1 sensor)
#   D5 — last_decision_time per UI coordinator (5 sensors)
#
# UI→emit mapping lives in coordinator_telemetry_const.py so adjusting it
# is a one-file change with no sensor-class touch.


class CoordinatorDecisionsTodaySensor(AggregationEntity, SensorEntity):
    """v4.6.13 D1: per-UI-coordinator decision count since local midnight.

    Entity: sensor.ura_{ui_coordinator}_decisions_today
    Refresh: SIGNAL_ACTIVITY_LOGGED, filtered by emit-label match.
    Cutoff: local midnight (Bug Class #11) converted to UTC isoformat.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:counter"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "decisions"

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, ui_coordinator: str,
    ) -> None:
        super().__init__(hass, entry)
        self._ui_coordinator = ui_coordinator
        self._attr_unique_id = f"{DOMAIN}_{ui_coordinator}_decisions_today"
        self._attr_name = f"{ui_coordinator.capitalize()} Decisions Today"
        self._attr_device_info = _cm_device_info()
        self._count_today: int = 0
        self._unsub_activity: object = None
        self._unsub_db_ready: object = None
        self._refresh_in_flight: bool = False
        self._refresh_pending: bool = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import (
            SIGNAL_ACTIVITY_LOGGED,
            SIGNAL_DATABASE_READY,
        )
        from .domain_coordinators.coordinator_telemetry_const import (
            COORDINATOR_EMIT_LABELS,
        )

        labels = COORDINATOR_EMIT_LABELS.get(self._ui_coordinator, ())

        def _handle_activity(payload: dict) -> None:
            # Filter by emit-label to avoid full-suite refresh on every activity row.
            if payload.get("coordinator") not in labels:
                return
            if self._refresh_in_flight:
                self._refresh_pending = True
            else:
                self.hass.add_job(self._async_refresh())

        self._unsub_activity = async_dispatcher_connect(
            self.hass, SIGNAL_ACTIVITY_LOGGED, _handle_activity
        )
        self.async_on_remove(
            lambda: self._unsub_activity() if self._unsub_activity else None
        )

        # v4.6.5.3 M2 pattern: event-driven initial load.
        if self.hass.data.get(DOMAIN, {}).get("database") is not None:
            await self._async_refresh()
        else:
            def _handle_db_ready(*_a, **_kw) -> None:
                self.hass.add_job(self._async_refresh())
                if self._unsub_db_ready is not None:
                    self._unsub_db_ready()
                    self._unsub_db_ready = None

            self._unsub_db_ready = async_dispatcher_connect(
                self.hass, SIGNAL_DATABASE_READY, _handle_db_ready
            )
            self.async_on_remove(
                lambda: self._unsub_db_ready()
                if self._unsub_db_ready is not None else None
            )

    async def _async_refresh(self) -> None:
        """Count activity_log rows since local midnight for mapped labels."""
        if self._refresh_in_flight:
            self._refresh_pending = True
            return
        self._refresh_in_flight = True
        try:
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database is None:
                return
            from .domain_coordinators.coordinator_telemetry_const import (
                COORDINATOR_EMIT_LABELS,
            )
            labels = COORDINATOR_EMIT_LABELS.get(self._ui_coordinator, ())
            if not labels:
                self._count_today = 0
                self.async_write_ha_state()
                return
            # Bug Class #11: midnight is LOCAL — use dt_util.start_of_local_day.
            local_midnight = dt_util.start_of_local_day()
            cutoff = dt_util.as_utc(local_midnight).isoformat()
            placeholders = ",".join("?" * len(labels))
            async with database._db_read() as db:
                cursor = await db.execute(
                    f"SELECT COUNT(*) FROM ura_activity_log "
                    f"WHERE coordinator IN ({placeholders}) "
                    f"AND timestamp >= ?",
                    (*labels, cutoff),
                )
                row = await cursor.fetchone()
                self._count_today = row[0] if row else 0
            self.async_write_ha_state()
        except Exception:
            _LOGGER.debug(
                "CoordinatorDecisionsTodaySensor(%s): refresh failed",
                self._ui_coordinator, exc_info=True,
            )
        finally:
            self._refresh_in_flight = False
            if self._refresh_pending:
                self._refresh_pending = False
                self.hass.async_create_task(self._async_refresh())

    @property
    def native_value(self) -> int:
        return self._count_today


class CoordinatorOverrideFrequencySensor(AggregationEntity, SensorEntity):
    """v4.6.13 D2: per-UI-coordinator override count over last 24h.

    Entity: sensor.ura_{ui_coordinator}_override_frequency
    Source: compliance_log.override_detected = 1 joined to decision_log.coordinator_id.
    Refresh: 5-minute polling (compliance writes don't dispatch signals).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:hand-back-left"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "overrides"

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, ui_coordinator: str,
    ) -> None:
        super().__init__(hass, entry)
        self._ui_coordinator = ui_coordinator
        self._attr_unique_id = f"{DOMAIN}_{ui_coordinator}_override_frequency"
        self._attr_name = f"{ui_coordinator.capitalize()} Override Frequency"
        self._attr_device_info = _cm_device_info()
        self._count_24h: int = 0
        self._unsub_timer: object = None
        self._unsub_db_ready: object = None  # Review B.B1/C.M2: db-ready fallback

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.event import async_track_time_interval
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.coordinator_telemetry_const import (
            OVERRIDE_FREQUENCY_REFRESH_S,
        )
        from .domain_coordinators.signals import SIGNAL_DATABASE_READY
        # Bug Class #38: capture unsub into async_on_remove.
        # Pass coroutine function directly — HA's HassJob machinery handles
        # thread-safe scheduling. Wrapping in a lambda + async_create_task
        # triggers HA's frame helper warning "calls async_create_task from a
        # thread other than the event loop, which may cause crash or data
        # corruption" and leaves the coroutine never-awaited (verified
        # 2026-05-26).
        self._unsub_timer = async_track_time_interval(
            self.hass,
            self._async_refresh,
            timedelta(seconds=OVERRIDE_FREQUENCY_REFRESH_S),
        )
        self.async_on_remove(
            lambda: self._unsub_timer() if self._unsub_timer else None
        )
        # Initial refresh — closes the v4.6.5.3 M2 startup race so the
        # 5-min poll-interval first-load delay is bounded by DB-ready
        # rather than the polling cadence (Review B.B1 / C.M2).
        if self.hass.data.get(DOMAIN, {}).get("database") is not None:
            await self._async_refresh()
        else:
            def _handle_db_ready(*_a, **_kw) -> None:
                # Bug Class #42 (v4.6.15) + v4.6.3.2 precedent:
                # use hass.add_job (thread-safe) NOT async_create_task in a
                # dispatcher-signal sync callback. SIGNAL_DATABASE_READY is
                # dispatched on-loop in this codebase today (verified Reviewer B
                # 2026-05-26), but the URARecentAnomaliesSensor v4.6.3.1
                # incident proved dispatchers CAN fire from non-event-loop
                # threads. add_job stays correct in either case.
                self.hass.add_job(self._async_refresh())
                if self._unsub_db_ready is not None:
                    self._unsub_db_ready()
                    self._unsub_db_ready = None

            self._unsub_db_ready = async_dispatcher_connect(
                self.hass, SIGNAL_DATABASE_READY, _handle_db_ready
            )
            self.async_on_remove(
                lambda: self._unsub_db_ready()
                if self._unsub_db_ready is not None else None
            )

    async def _async_refresh(self, _now=None) -> None:
        """Recompute override-frequency rolling count.

        `_now` parameter accepts the datetime passed by HA's
        async_track_time_interval scheduler. Default None for the
        in-process initial-refresh call.
        """
        try:
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database is None:
                return
            from .domain_coordinators.coordinator_telemetry_const import (
                COORDINATOR_EMIT_LABELS,
                OVERRIDE_FREQUENCY_WINDOW_HOURS,
            )
            labels = COORDINATOR_EMIT_LABELS.get(self._ui_coordinator, ())
            if not labels:
                self._count_24h = 0
                self.async_write_ha_state()
                return
            # Bug Class #21: compliance_log.timestamp is tz-naive (database.py
            # uses datetime.utcnow().isoformat() for writes). Strip tzinfo
            # from cutoff to match the stored shape.
            cutoff = (
                dt_util.utcnow() - timedelta(hours=OVERRIDE_FREQUENCY_WINDOW_HOURS)
            ).replace(tzinfo=None).isoformat()
            placeholders = ",".join("?" * len(labels))
            async with database._db_read() as db:
                cursor = await db.execute(
                    f"""SELECT COUNT(*) FROM compliance_log c
                        JOIN decision_log d ON c.decision_id = d.id
                        WHERE c.override_detected = 1
                          AND d.coordinator_id IN ({placeholders})
                          AND c.timestamp >= ?""",
                    (*labels, cutoff),
                )
                row = await cursor.fetchone()
                self._count_24h = row[0] if row else 0
            self.async_write_ha_state()
        except Exception:
            _LOGGER.debug(
                "CoordinatorOverrideFrequencySensor(%s): refresh failed",
                self._ui_coordinator, exc_info=True,
            )

    @property
    def native_value(self) -> int:
        return self._count_24h

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        from .domain_coordinators.coordinator_telemetry_const import (
            OVERRIDE_FREQUENCY_WINDOW_HOURS,
        )
        return {"window_hours": OVERRIDE_FREQUENCY_WINDOW_HOURS}


class CoordinatorComplianceRateSensor(AggregationEntity, SensorEntity):
    """v4.6.13 D3: per-UI-coordinator 7-day compliance percentage.

    Entity: sensor.ura_{ui_coordinator}_compliance_rate
    Source: existing ComplianceTracker.get_compliance_rate DAO. For UI
    coordinators mapped to multiple emit-labels (e.g. presence → presence
    + transit + room), aggregate by summing compliant + total across labels.
    Returns None when no decisions in window (avoids misleading "100%" on
    fresh install).
    Refresh: 30-minute polling (compliance rate is slow-moving 7-day metric).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:check-decagram"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, ui_coordinator: str,
    ) -> None:
        super().__init__(hass, entry)
        self._ui_coordinator = ui_coordinator
        self._attr_unique_id = f"{DOMAIN}_{ui_coordinator}_compliance_rate"
        self._attr_name = f"{ui_coordinator.capitalize()} Compliance Rate"
        self._attr_device_info = _cm_device_info()
        self._rate_pct: int | None = None
        self._decisions_in_window: int = 0
        self._unsub_timer: object = None
        self._unsub_db_ready: object = None  # Review B.B1/C.M2: db-ready fallback

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.event import async_track_time_interval
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.coordinator_telemetry_const import (
            COMPLIANCE_RATE_REFRESH_S,
        )
        from .domain_coordinators.signals import SIGNAL_DATABASE_READY
        # Pass coroutine function directly — see CoordinatorOverrideFrequencySensor
        # for rationale (frame-helper warning + never-awaited coroutine bug).
        self._unsub_timer = async_track_time_interval(
            self.hass,
            self._async_refresh,
            timedelta(seconds=COMPLIANCE_RATE_REFRESH_S),
        )
        self.async_on_remove(
            lambda: self._unsub_timer() if self._unsub_timer else None
        )
        # Review B.B1/C.M2: DB-ready fallback — 30-min poll interval would
        # leave the sensor at "unknown" too long if the DB initializes after
        # this sensor's async_added_to_hass.
        if self.hass.data.get(DOMAIN, {}).get("database") is not None:
            await self._async_refresh()
        else:
            def _handle_db_ready(*_a, **_kw) -> None:
                # Bug Class #42 (v4.6.15) + v4.6.3.2 precedent:
                # use hass.add_job (thread-safe) NOT async_create_task in a
                # dispatcher-signal sync callback. SIGNAL_DATABASE_READY is
                # dispatched on-loop in this codebase today (verified Reviewer B
                # 2026-05-26), but the URARecentAnomaliesSensor v4.6.3.1
                # incident proved dispatchers CAN fire from non-event-loop
                # threads. add_job stays correct in either case.
                self.hass.add_job(self._async_refresh())
                if self._unsub_db_ready is not None:
                    self._unsub_db_ready()
                    self._unsub_db_ready = None

            self._unsub_db_ready = async_dispatcher_connect(
                self.hass, SIGNAL_DATABASE_READY, _handle_db_ready
            )
            self.async_on_remove(
                lambda: self._unsub_db_ready()
                if self._unsub_db_ready is not None else None
            )

    async def _async_refresh(self, _now=None) -> None:
        """Aggregate get_compliance_rate across mapped emit-labels.

        `_now` parameter accepts the datetime passed by HA's
        async_track_time_interval scheduler when called as the timer
        callback. Default None for the in-process initial-refresh call.
        """
        try:
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database is None:
                return
            from .domain_coordinators.coordinator_telemetry_const import (
                COORDINATOR_EMIT_LABELS,
                COMPLIANCE_RATE_WINDOW_DAYS,
            )
            labels = COORDINATOR_EMIT_LABELS.get(self._ui_coordinator, ())
            if not labels:
                self._rate_pct = None
                self._decisions_in_window = 0
                self.async_write_ha_state()
                return

            # Parallel SELECT COUNT(*) to gate "no decisions → None" — DAO
            # returns 1.0 for empty (foot-gun), so we count separately.
            # Bug Class #21: compliance_log.timestamp is tz-naive.
            cutoff = (
                dt_util.utcnow() - timedelta(days=COMPLIANCE_RATE_WINDOW_DAYS)
            ).replace(tzinfo=None).isoformat()
            placeholders = ",".join("?" * len(labels))
            total = 0
            compliant = 0
            async with database._db_read() as db:
                cursor = await db.execute(
                    f"""SELECT COUNT(*),
                              SUM(CASE WHEN c.compliant THEN 1 ELSE 0 END)
                       FROM compliance_log c
                       JOIN decision_log d ON c.decision_id = d.id
                       WHERE c.timestamp >= ?
                         AND d.coordinator_id IN ({placeholders})""",
                    (cutoff, *labels),
                )
                row = await cursor.fetchone()
                if row:
                    total = int(row[0] or 0)
                    compliant = int(row[1] or 0)

            self._decisions_in_window = total
            if total == 0:
                self._rate_pct = None  # HA renders "unknown" — honest signal
            else:
                self._rate_pct = int(round((compliant / total) * 100))
            self.async_write_ha_state()
        except Exception:
            _LOGGER.debug(
                "CoordinatorComplianceRateSensor(%s): refresh failed",
                self._ui_coordinator, exc_info=True,
            )

    @property
    def native_value(self) -> int | None:
        return self._rate_pct

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        from .domain_coordinators.coordinator_telemetry_const import (
            COMPLIANCE_RATE_WINDOW_DAYS,
        )
        return {
            "decisions_in_window": self._decisions_in_window,
            "window_days": COMPLIANCE_RATE_WINDOW_DAYS,
        }


class URADBSizeSensor(AggregationEntity, SensorEntity):
    """v4.6.13 D4: URA SQLite DB size in MB (including WAL + SHM sidecars).

    Entity: sensor.ura_db_size_mb
    Refresh: 5-minute polling (filesystem stat — no DB query).
    Includes WAL/SHM sidecars since they can be 100s of MB during heavy
    write bursts and the user-meaningful "DB size" must include them.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:database"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "MB"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_db_size_mb"
        self._attr_name = "DB Size"
        self._attr_device_info = _cm_device_info()
        self._size_mb: float | None = None
        self._unsub_timer: object = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.event import async_track_time_interval
        from .domain_coordinators.coordinator_telemetry_const import (
            DB_SIZE_REFRESH_S,
        )
        # Pass coroutine function directly — see CoordinatorOverrideFrequencySensor
        # for rationale (frame-helper warning + never-awaited coroutine bug).
        self._unsub_timer = async_track_time_interval(
            self.hass,
            self._async_refresh,
            timedelta(seconds=DB_SIZE_REFRESH_S),
        )
        self.async_on_remove(
            lambda: self._unsub_timer() if self._unsub_timer else None
        )
        await self._async_refresh()

    async def _async_refresh(self, _now=None) -> None:
        """Refresh DB size from filesystem stat (no DB query).

        `_now` parameter accepts the datetime passed by HA's
        async_track_time_interval scheduler. Default None for the
        in-process initial-refresh call.
        """
        import os
        try:
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database is None:
                self._size_mb = None
                self.async_write_ha_state()
                return
            db_path = getattr(database, "db_file", None)
            if not db_path:
                self._size_mb = None
                self.async_write_ha_state()
                return
            size_bytes = await self.hass.async_add_executor_job(
                os.path.getsize, db_path
            )
            # Include WAL + SHM sidecars (WAL mode).
            for suffix in ("-wal", "-shm"):
                try:
                    size_bytes += await self.hass.async_add_executor_job(
                        os.path.getsize, db_path + suffix
                    )
                except OSError:
                    pass  # WAL/SHM may not exist between checkpoints
            self._size_mb = round(size_bytes / (1024 * 1024), 2)
            self.async_write_ha_state()
        except FileNotFoundError:
            self._size_mb = None
            self.async_write_ha_state()
        except Exception:
            _LOGGER.debug("URADBSizeSensor: refresh failed", exc_info=True)

    @property
    def native_value(self) -> float | None:
        return self._size_mb


class CoordinatorLastDecisionSensor(AggregationEntity, SensorEntity):
    """v4.6.13 D5: per-UI-coordinator last-decision timestamp + context.

    Entity: sensor.ura_{ui_coordinator}_last_decision_time
    Refresh: SIGNAL_ACTIVITY_LOGGED, filtered by emit-label match.
    State: timestamp of most recent activity_log row across mapped labels.
    Attributes: action, description, room, zone, entity_id of that row.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, ui_coordinator: str,
    ) -> None:
        super().__init__(hass, entry)
        self._ui_coordinator = ui_coordinator
        self._attr_unique_id = f"{DOMAIN}_{ui_coordinator}_last_decision_time"
        self._attr_name = f"{ui_coordinator.capitalize()} Last Decision"
        self._attr_device_info = _cm_device_info()
        self._last_ts: datetime | None = None
        self._last_attrs: dict[str, Any] = {}
        self._unsub_activity: object = None
        self._unsub_db_ready: object = None
        self._refresh_in_flight: bool = False
        self._refresh_pending: bool = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import (
            SIGNAL_ACTIVITY_LOGGED,
            SIGNAL_DATABASE_READY,
        )
        from .domain_coordinators.coordinator_telemetry_const import (
            COORDINATOR_EMIT_LABELS,
        )

        labels = COORDINATOR_EMIT_LABELS.get(self._ui_coordinator, ())

        def _handle_activity(payload: dict) -> None:
            if payload.get("coordinator") not in labels:
                return
            if self._refresh_in_flight:
                self._refresh_pending = True
            else:
                self.hass.add_job(self._async_refresh())

        self._unsub_activity = async_dispatcher_connect(
            self.hass, SIGNAL_ACTIVITY_LOGGED, _handle_activity
        )
        self.async_on_remove(
            lambda: self._unsub_activity() if self._unsub_activity else None
        )

        if self.hass.data.get(DOMAIN, {}).get("database") is not None:
            await self._async_refresh()
        else:
            def _handle_db_ready(*_a, **_kw) -> None:
                self.hass.add_job(self._async_refresh())
                if self._unsub_db_ready is not None:
                    self._unsub_db_ready()
                    self._unsub_db_ready = None

            self._unsub_db_ready = async_dispatcher_connect(
                self.hass, SIGNAL_DATABASE_READY, _handle_db_ready
            )
            self.async_on_remove(
                lambda: self._unsub_db_ready()
                if self._unsub_db_ready is not None else None
            )

    async def _async_refresh(self) -> None:
        if self._refresh_in_flight:
            self._refresh_pending = True
            return
        self._refresh_in_flight = True
        try:
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database is None:
                return
            from .domain_coordinators.coordinator_telemetry_const import (
                COORDINATOR_EMIT_LABELS,
            )
            labels = COORDINATOR_EMIT_LABELS.get(self._ui_coordinator, ())
            if not labels:
                self._last_ts = None
                self._last_attrs = {}
                self.async_write_ha_state()
                return
            placeholders = ",".join("?" * len(labels))
            async with database._db_read() as db:
                cursor = await db.execute(
                    f"""SELECT timestamp, action, description, room,
                              zone, entity_id
                       FROM ura_activity_log
                       WHERE coordinator IN ({placeholders})
                       ORDER BY timestamp DESC
                       LIMIT 1""",
                    labels,
                )
                row = await cursor.fetchone()
                if row is None:
                    self._last_ts = None
                    self._last_attrs = {}
                else:
                    # Bug Class #21: ura_activity_log writes are tz-aware.
                    self._last_ts = dt_util.parse_datetime(row[0])
                    self._last_attrs = {
                        "action": row[1],
                        "description": row[2],
                        "room": row[3],
                        "zone": row[4],
                        "entity_id": row[5],
                    }
            self.async_write_ha_state()
        except Exception:
            _LOGGER.debug(
                "CoordinatorLastDecisionSensor(%s): refresh failed",
                self._ui_coordinator, exc_info=True,
            )
        finally:
            self._refresh_in_flight = False
            if self._refresh_pending:
                self._refresh_pending = False
                self.hass.async_create_task(self._async_refresh())

    @property
    def native_value(self) -> datetime | None:
        return self._last_ts

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._last_attrs)



# =============================================================================
# v4.7.8 D5 — Egress Window HVAC Pause sensors (end-of-file append)
# -----------------------------------------------------------------------------
# All sensors read from in-memory EgressManager state — NO DB read on
# async_update (Bug Class #26).
# =============================================================================


class HVACZoneEgressStateSensor(SensorEntity):
    """State-machine label per canonical HVAC zone (v4.7.8 D5).

    Reads in-memory state from EgressManager.state_label / get_zone_info.
    No DB I/O on async_update (Bug Class #26). Updates via the existing
    SIGNAL_HVAC_ENTITIES_UPDATE tick.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:gate-open"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        zone_id: str,
        zone_name: str,
    ) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self.hass = hass
        self._entry = entry
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._attr_unique_id = f"{DOMAIN}_hvac_zone_{zone_id}_egress_state"
        self._attr_name = f"{zone_name} Egress State"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_egress(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return None
        return getattr(hvac, "egress_manager", None)

    @property
    def native_value(self) -> str | None:
        em = self._get_egress()
        if em is None:
            return "idle"
        try:
            return em.state_label(self._zone_id)
        except Exception:
            return "idle"

    @property
    def extra_state_attributes(self) -> dict:
        em = self._get_egress()
        if em is None:
            return {"zone_id": self._zone_id}
        try:
            info = em.get_zone_info(self._zone_id)
            info["zone_id"] = self._zone_id
            return info
        except Exception:
            return {"zone_id": self._zone_id}

    @property
    def available(self) -> bool:
        return self._get_egress() is not None

    async def async_added_to_hass(self) -> None:
        """Refresh on every HVAC tick."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE

        @callback
        def _on_update(*_a, **_kw):
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, _on_update)
        )


class HVACEgressPausedZonesSensor(SensorEntity):
    """Global count of zones currently paused by EgressManager (v4.7.8 D5)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:pause-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self.hass = hass
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_hvac_egress_paused_zones"
        self._attr_name = "Egress Paused Zones"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_egress(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return None
        return getattr(hvac, "egress_manager", None)

    @property
    def native_value(self) -> int:
        em = self._get_egress()
        if em is None:
            return 0
        try:
            return len(em.paused_zones())
        except Exception:
            return 0

    @property
    def extra_state_attributes(self) -> dict:
        em = self._get_egress()
        if em is None:
            return {"paused_zones": [], "cooldowns": {}}
        try:
            return {
                "paused_zones": em.paused_zones(),
                "cooldowns": em.get_cooldowns(),
            }
        except Exception:
            return {"paused_zones": [], "cooldowns": {}}

    @property
    def available(self) -> bool:
        return self._get_egress() is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE

        @callback
        def _on_update(*_a, **_kw):
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, _on_update)
        )


# =============================================================================
# Fan-noise Mode-2 — per-room diagnostic sensors
# -----------------------------------------------------------------------------
# Both disabled by default in entity registry. Native value reads
# FanRecheckManager.get_room_attrs(room_name) each access; no listener
# wiring (UI poll cadence is sufficient and avoids per-room dispatch
# subscriptions for an opt-in operability surface).
# =============================================================================


def _fan_recheck_attrs_for(hass: HomeAssistant, room_name: str) -> dict:
    """Read FanRecheckManager attrs for a room. Defensive — never raises."""
    try:
        manager = hass.data.get(DOMAIN, {}).get("coordinator_manager")
        presence = (
            manager.coordinators.get("presence") if manager else None
        )
        fr_mgr = (
            getattr(presence, "_fan_recheck_manager", None)
            if presence is not None else None
        )
        if fr_mgr is None or not room_name:
            return {}
        return fr_mgr.get_room_attrs(room_name) or {}
    except Exception:  # noqa: BLE001
        return {}


class RoomFanRecheckStateSensor(UniversalRoomEntity, SensorEntity):
    """Current fan-recheck state for this room (idle/armed/paused/...)."""

    _attr_icon = "mdi:fan-clock"
    _attr_entity_registry_enabled_default = False
    # Review H1 (2026-07-18): the two observability counters
    # ``fan_recheck_eval_count`` + ``fan_recheck_veto_counts`` are strictly
    # monotonic (they only increment) and would create one recorder state
    # row per coordinator update once the sensor is enabled during the
    # 2-4 week data harvest. Exclude them from recorder history via HA's
    # per-entity ``_unrecorded_attributes`` frozenset — verified at
    # ``homeassistant/helpers/entity.py:518`` in the installed HA source
    # (v.venv-ha, python3.13 site-packages). Live attrs still visible;
    # only the recorder skips them.
    _unrecorded_attributes = frozenset({
        "fan_recheck_eval_count",
        "fan_recheck_veto_counts",
    })

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        super().__init__(
            coordinator, "fan_recheck_state", "Fan Recheck State",
        )

    @property
    def native_value(self) -> str:
        attrs = _fan_recheck_attrs_for(
            self.hass,
            self.coordinator.entry.data.get("room_name", ""),
        )
        return str(attrs.get("fan_recheck_state", "idle"))

    @property
    def extra_state_attributes(self) -> dict:
        attrs = _fan_recheck_attrs_for(
            self.hass,
            self.coordinator.entry.data.get("room_name", ""),
        )
        return {
            "fan_recheck_ble_ladder_layer": attrs.get(
                "fan_recheck_ble_ladder_layer", "none",
            ),
            "fan_recheck_last_attempt_iso": attrs.get(
                "fan_recheck_last_attempt_iso",
            ),
            # Observability (RAM-only, since-boot). Durable events live in
            # ura_activity_log rows (fan_recheck_arm/outcome/cancel).
            "fan_recheck_eval_count": attrs.get(
                "fan_recheck_eval_count", 0,
            ),
            "fan_recheck_veto_counts": attrs.get(
                "fan_recheck_veto_counts", {},
            ),
        }


class RoomFanRecheckLastOutcomeSensor(UniversalRoomEntity, SensorEntity):
    """Outcome of the last fan-recheck (vacated / occupied_confirmed / None)."""

    _attr_icon = "mdi:fan-chevron-down"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        super().__init__(
            coordinator, "fan_recheck_last_outcome", "Fan Recheck Last Outcome",
        )

    @property
    def native_value(self) -> Optional[str]:
        attrs = _fan_recheck_attrs_for(
            self.hass,
            self.coordinator.entry.data.get("room_name", ""),
        )
        outcome = attrs.get("fan_recheck_last_outcome")
        return outcome if outcome else None

    @property
    def extra_state_attributes(self) -> dict:
        attrs = _fan_recheck_attrs_for(
            self.hass,
            self.coordinator.entry.data.get("room_name", ""),
        )
        return {
            "fan_recheck_last_attempt_iso": attrs.get(
                "fan_recheck_last_attempt_iso",
            ),
        }


# ============================================================================
# v4.7.34 Phase 1 D7: Optimization Coordinator sensors
# ============================================================================
#
# Pattern (Bug Class #50 + #5 safe):
# - Subscribe in async_added_to_hass to SIGNAL_OPTIMIZER_FINDING_EMITTED.
# - Store the unsub on `self._signal_unsubs` (and via async_on_remove so
#   HA tears it down on remove). Periodic rebuilds do NOT clear this list.
# - Initial state = "(initializing)" — first cycle populates real values.


def _optimizer_device_info():
    """Return the URA: Optimization Coordinator device_info."""
    from homeassistant.helpers.device_registry import DeviceInfo
    return DeviceInfo(
        identifiers={(DOMAIN, "optimization_coordinator")},
        name="URA: Optimization Coordinator",
        manufacturer="Universal Room Automation",
        model="Optimization Coordinator",
        sw_version="v4.7.33",
        via_device=(DOMAIN, "coordinator_manager"),
    )


class _OptimizerCMSensorBase(SensorEntity):
    """Base for CM-device-resident optimizer sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._attr_device_info = _optimizer_device_info()
        self._signal_unsubs: list = []

    def _get_coord(self):
        """Return the OptimizationCoordinator if present."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        try:
            return manager.coordinators.get("optimization")
        except Exception:
            return None

    async def async_added_to_hass(self) -> None:
        """Subscribe to finding-emitted signal — Bug Class #50 safe."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_OPTIMIZER_FINDING_EMITTED

        @callback
        def _on_finding(_payload=None):
            self.async_write_ha_state()

        unsub = async_dispatcher_connect(
            self.hass, SIGNAL_OPTIMIZER_FINDING_EMITTED, _on_finding,
        )
        self._signal_unsubs.append(unsub)
        # async_on_remove ensures HA tears it down on entity remove;
        # storing on self._signal_unsubs makes the rebuild-safe property
        # explicit (Bug Class #50). Both safety nets present.
        self.async_on_remove(unsub)

    async def async_will_remove_from_hass(self) -> None:
        for u in list(self._signal_unsubs):
            try:
                u()
            except Exception:
                pass
        self._signal_unsubs.clear()
        await super().async_will_remove_from_hass()


class OptimizerStatusSensor(_OptimizerCMSensorBase):
    """sensor.ura_optimizer_status — overall health gauge.

    State ∈ {healthy, degraded, critical, paused}.
    """

    _attr_icon = "mdi:tune-vertical"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_optimizer_status"
        self._attr_name = "Optimizer Status"
        # Bug Class #5: register with placeholder, first cycle populates.
        self._attr_native_value = "initializing"

    @property
    def native_value(self) -> str:
        coord = self._get_coord()
        if coord is None:
            return "initializing"
        try:
            return coord.status
        except Exception:
            return "initializing"

    @property
    def extra_state_attributes(self) -> dict:
        coord = self._get_coord()
        if coord is None:
            return {"mode": "shadow"}
        from .const import (
            DEFAULT_OPTIMIZER_AUTONOMY_LEVEL,
            CONF_OPTIMIZER_AUTONOMY_LEVEL,
            CONF_OPTIMIZER_DIMENSION_AUTONOMY,
            CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL,
            SCAN_INTERVAL_OPTIMIZATION,
        )
        try:
            cfg = coord._read_cm_config()
        except Exception:
            cfg = {}
        last_findings = list(getattr(coord, "_last_findings", []) or [])
        # Pillar B D5 fix: split window vs last-cycle so dashboards
        # consume the same authoritative count regardless of cycle phase.
        last_cycle_findings_count = len(last_findings)
        window_findings_count = getattr(coord, "_open_findings_count", 0)
        window_house_score = getattr(coord, "_house_score", 100.0)
        # next_cycle_eta_seconds — seconds until next 5-min cycle tick,
        # derived from the last-evaluation ISO. Never negative.
        next_eta: int | None = None
        try:
            last_iso = getattr(coord, "_last_evaluation_iso", None)
            if last_iso:
                from datetime import datetime as _dt
                last_dt = _dt.fromisoformat(str(last_iso))
                from homeassistant.util import dt as _dt_util
                now_dt = _dt_util.utcnow()
                if last_dt.tzinfo is None and now_dt.tzinfo is not None:
                    last_dt = last_dt.replace(tzinfo=now_dt.tzinfo)
                elapsed = (now_dt - last_dt).total_seconds()
                interval = SCAN_INTERVAL_OPTIMIZATION.total_seconds()
                next_eta = max(0, int(interval - elapsed))
        except Exception:
            next_eta = None
        # last_action — reverse-scan _last_findings for the most recent
        # outcome=="applied" entry; empty dict at L1 / shadow.
        last_action: dict = {}
        try:
            for f in reversed(last_findings):
                if getattr(f, "applied_outcome", None) == "applied":
                    target_entity = None
                    if isinstance(f.proposed_action, dict):
                        target_entity = (
                            f.proposed_action.get("target_entity")
                            or f.proposed_action.get("entity_id")
                        )
                    last_action = {
                        "action_id": getattr(f, "applied_action_id", None),
                        "target_entity": target_entity,
                        "dimension": str(f.dimension),
                        "dispatched_at_iso": f.timestamp,
                    }
                    break
        except Exception:
            last_action = {}
        # llm_invocations_today — Pillar B fix-up A-M8: filter the
        # ``_premium_invocations`` list to the trailing-24h window at
        # READ time. The list contains UTC datetimes (verified in
        # optimization_llm.py:229; appended at :346) which are evicted
        # lazily on the next ``_premium_cycle_ok`` check — so reading
        # ``len(inv)`` directly can overcount briefly between cycles.
        # NB: This is a deliberate private-attr coupling. The LLM tier
        # owns the list; the sensor is a read-only display surface.
        llm_invocations_today = 0
        try:
            tier = getattr(coord, "_llm_tier", None)
            if tier is not None:
                inv = getattr(tier, "_premium_invocations", None)
                if inv is not None:
                    from homeassistant.util import dt as _dt_util_llm
                    from datetime import timedelta as _td_llm
                    cutoff_llm = _dt_util_llm.utcnow() - _td_llm(hours=24)
                    count = 0
                    for ts in inv:
                        try:
                            ts_cmp = ts
                            if (
                                cutoff_llm.tzinfo is None
                                and getattr(ts_cmp, "tzinfo", None) is not None
                            ):
                                ts_cmp = ts_cmp.replace(tzinfo=None)
                            elif (
                                cutoff_llm.tzinfo is not None
                                and getattr(ts_cmp, "tzinfo", None) is None
                            ):
                                ts_cmp = ts_cmp.replace(tzinfo=cutoff_llm.tzinfo)
                            if ts_cmp >= cutoff_llm:
                                count += 1
                        except Exception:  # noqa: BLE001
                            # Non-datetime entries (legacy / test stubs):
                            # count them so opaque payloads don't silently
                            # drop. Keeps the attr conservative.
                            count += 1
                    llm_invocations_today = count
        except Exception:
            llm_invocations_today = 0
        # Pillar B fix-up A-M7 / B-L2: surface BOTH the raw per-dimension
        # caps (`dimension_autonomy_caps`) AND the merged effective
        # per-dim level (`effective_level_per_dim`). Merge rule:
        # min(rank(committed_level), rank(per_dim_cap)) mapped back to
        # the level token. This matches the attr name and the plan —
        # the old impl just echoed the caps which lied about what level
        # the dimension would actually run at when caps > committed.
        dimension_autonomy_caps: dict[str, str] = {}
        effective_level_per_dim: dict[str, str] = {}
        try:
            from .const import (
                OPTIMIZER_LEVEL_RANK as _LVL_RANK,
                OPTIMIZER_AUTONOMY_LEVELS as _LVLS,
            )
            dim_caps = cfg.get(CONF_OPTIMIZER_DIMENSION_AUTONOMY) or {}
            if isinstance(dim_caps, dict):
                dimension_autonomy_caps = {
                    str(k): str(v) for k, v in dim_caps.items()
                }
                committed_level = cfg.get(
                    CONF_OPTIMIZER_AUTONOMY_LEVEL,
                    DEFAULT_OPTIMIZER_AUTONOMY_LEVEL,
                )
                committed_rank = _LVL_RANK.get(committed_level, 0)
                # Build reverse map rank → token for the merge result.
                rank_to_level = {
                    _LVL_RANK.get(lvl, 0): lvl for lvl in _LVLS
                }
                for dim, cap_lvl in dimension_autonomy_caps.items():
                    cap_rank = _LVL_RANK.get(cap_lvl, committed_rank)
                    merged_rank = min(committed_rank, cap_rank)
                    effective_level_per_dim[dim] = rank_to_level.get(
                        merged_rank, committed_level,
                    )
        except Exception:
            dimension_autonomy_caps = {}
            effective_level_per_dim = {}
        # v5.4 D2b/D2d — additive attrs (dimension_verdicts +
        # shadow_accuracy_pct / status). All defensive reads so a stale
        # coordinator returns safe sentinels rather than raising.
        dimension_verdicts: dict[str, str] = {}
        try:
            verdicts = getattr(coord, "_last_dimension_verdicts", None)
            if isinstance(verdicts, dict):
                dimension_verdicts = dict(verdicts)
        except Exception:
            dimension_verdicts = {}
        try:
            shadow_pct = getattr(coord, "_last_shadow_accuracy_pct", None)
        except Exception:
            shadow_pct = None
        try:
            shadow_status = getattr(
                coord, "_last_shadow_accuracy_status", "warming_up",
            )
        except Exception:
            shadow_status = "warming_up"
        return {
            "autonomy_level": cfg.get(
                CONF_OPTIMIZER_AUTONOMY_LEVEL, DEFAULT_OPTIMIZER_AUTONOMY_LEVEL,
            ),
            "pending_autonomy_level": cfg.get(
                CONF_OPTIMIZER_PENDING_AUTONOMY_LEVEL,
            ),
            "effective_level": getattr(coord, "effective_level",
                                       DEFAULT_OPTIMIZER_AUTONOMY_LEVEL),
            "effective_level_per_dim": effective_level_per_dim,
            "dimension_autonomy_caps": dimension_autonomy_caps,
            "mode": getattr(coord, "effective_level",
                            DEFAULT_OPTIMIZER_AUTONOMY_LEVEL),
            # Latest cycle (authoritative for "is the optimizer happy
            # RIGHT NOW") — fixes the v5.x cosmetic disagreement with
            # the findings sensor.
            "last_cycle_findings_count": last_cycle_findings_count,
            "last_cycle_finished_at": getattr(
                coord, "_last_evaluation_iso", None,
            ),
            # Rolling window (kept for trend dashboards).
            "window_findings_count": window_findings_count,
            "window_house_score": window_house_score,
            "house_score": window_house_score,  # back-compat alias
            "last_evaluation": getattr(coord, "_last_evaluation_iso", None),
            "next_cycle_eta_seconds": next_eta,
            "last_action": last_action,
            "rate_cap_window_count": coord._rate_cap_window_count(),
            "quiet_hours_active": coord._is_quiet_hours_active(),
            "llm_invocations_today": llm_invocations_today,
            # v5.4 D2b — per-dimension verdicts for this cycle.
            "dimension_verdicts": dimension_verdicts,
            # v5.4 D2d — rolling shadow-accuracy gauge.
            "shadow_accuracy_pct": shadow_pct,
            "shadow_accuracy_status": shadow_status,
        }


class OptimizerFindingsSensor(_OptimizerCMSensorBase):
    """sensor.ura_optimizer_findings — latest finding description + recent list."""

    _attr_icon = "mdi:format-list-bulleted"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_optimizer_findings"
        self._attr_name = "Optimizer Findings"
        self._attr_native_value = "initializing"

    @property
    def native_value(self) -> str:
        coord = self._get_coord()
        if coord is None or not coord._last_findings:
            return "initializing"
        # v5.11.0 D7 — exclude META sentinel from the display state so
        # the operator's timeline doesn't flip to "cycle_ok" on every
        # quiet cycle. META rows still persist to the DB (Review-D
        # anchor) but don't pollute the visible state.
        for f in reversed(coord._last_findings):
            if str(f.dimension) != "meta":
                return f.description[:255]
        # Only META rows this cycle → truly quiet; state reflects that.
        return "cycle_ok"

    @property
    def extra_state_attributes(self) -> dict:
        coord = self._get_coord()
        if coord is None:
            return {"findings": [], "by_severity": {}, "by_level": {}}
        # Most-recent 20 findings.
        recent = coord._last_findings[-20:]
        findings_list = [
            {
                "timestamp": f.timestamp,
                "level": f.level,
                "target_id": f.target_id,
                "dimension": str(f.dimension),
                "severity": f.severity,
                "description": f.description,
                "applied_outcome": f.applied_outcome,
            }
            for f in recent
        ]
        summary = coord.get_open_findings_summary()
        # Pillar B D5: surface the Phase-4 prediction-vs-actual score for
        # the most recent applied finding (if Phase-4 populated it).
        last_action_outcome_score = None
        try:
            for f in reversed(recent):
                if getattr(f, "applied_outcome", None) == "applied":
                    obs = getattr(f, "observed_effect", None)
                    if isinstance(obs, dict):
                        last_action_outcome_score = (
                            obs.get("outcome_score")
                            or obs.get("score")
                        )
                    break
        except Exception:
            last_action_outcome_score = None
        # v5.4 D2c — surface the LLM-emitted findings' reasoning prose
        # for the most recent cycle. Hard-capped (20 entries, 512 chars
        # per `reasoning`) and bounded to LLM-sourced rows only so a
        # Tier-1 cycle with zero LLM emits doesn't add noise.
        llm_reasoning_summary: list[dict] = []
        try:
            for f in recent:
                if getattr(f, "created_by", "") != "tier2_llm":
                    continue
                llm_reasoning_summary.append({
                    "target_id": f.target_id,
                    "dimension": str(f.dimension),
                    "severity": f.severity,
                    "description": (f.description or "")[:255],
                    "reasoning": (getattr(f, "reasoning", "") or "")[:512],
                })
                if len(llm_reasoning_summary) >= 20:
                    break
        except Exception:
            llm_reasoning_summary = []
        return {
            "findings": findings_list,
            "by_severity": summary["by_severity"],
            "by_level": summary["by_level"],
            "last_action_outcome_score": last_action_outcome_score,
            "llm_reasoning_summary": llm_reasoning_summary,
        }


class OptimizerReasoningSensor(_OptimizerCMSensorBase):
    """sensor.ura_optimizer_reasoning — plain-English per-cycle commentary.

    v5.4 D2a. State = short headline ("cycle ok — N findings, M high");
    attrs carry the per-cycle reasoning structure that dashboards can
    surface standalone:

      cycle_summary: multi-line per-dimension verdict text (≤1024 chars).
      cycle_actions_proposed: capped list of {dimension, severity,
        target, action, outcome, predicted_effect}.
      dry_run_veto_count: rolling count of pending vetoes against this
        cycle's intents (from OptimizerIntentBroker._pending_vetoes).
      last_cycle_at: ISO of last evaluation.

    Recorder-bounded: state changes at most once per OC cycle (5 min).
    """

    _attr_icon = "mdi:robot-confused"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_optimizer_reasoning"
        self._attr_name = "Optimizer Reasoning"
        self._attr_native_value = "initializing"

    @property
    def native_value(self) -> str:
        coord = self._get_coord()
        if coord is None:
            return "initializing"
        summary = getattr(coord, "_last_cycle_summary", "") or ""
        if not summary:
            return "initializing"
        # First line of the summary serves as the headline state.
        return summary.split("\n", 1)[0][:255]

    @property
    def extra_state_attributes(self) -> dict:
        coord = self._get_coord()
        if coord is None:
            return {
                "cycle_summary": "",
                "cycle_actions_proposed": [],
                "dry_run_veto_count": 0,
                "last_cycle_at": None,
            }
        try:
            cycle_summary = getattr(coord, "_last_cycle_summary", "") or ""
        except Exception:
            cycle_summary = ""
        try:
            actions = list(
                getattr(coord, "_last_cycle_actions_proposed", []) or []
            )[:20]
        except Exception:
            actions = []
        try:
            veto_count = int(getattr(coord, "dry_run_veto_count", 0))
        except Exception:
            veto_count = 0
        # v5.11.0 — observability attrs (D9 tripwire, D1 dedup keys,
        # D4 boot-storm cache, D2 shadow-sample count, D6 promotion
        # readiness). Per critique's binding decision, NEW sensor
        # entities are NOT created; these ride on the existing
        # reasoning sensor.
        notify_dedup_active_keys = 0
        try:
            notify_dedup_active_keys = len(
                getattr(coord, "_notify_dedup_state", {}) or {}
            )
        except Exception:
            notify_dedup_active_keys = 0
        try:
            shadow_samples_count = len(
                getattr(coord, "_shadow_accuracy_samples", []) or []
            )
        except Exception:
            shadow_samples_count = 0
        promotion_readiness: dict = {}
        try:
            if hasattr(coord, "_compute_promotion_readiness"):
                promotion_readiness = coord._compute_promotion_readiness()
        except Exception:
            promotion_readiness = {}
        return {
            "cycle_summary": cycle_summary[:1024],
            "cycle_actions_proposed": actions,
            "dry_run_veto_count": veto_count,
            "last_cycle_at": getattr(coord, "_last_evaluation_iso", None),
            # v5.11.0 D9 — write-volume tripwire observability.
            "write_volume_alarmed_at": getattr(
                coord, "_write_volume_alarmed_at", None
            ),
            "persistence_suspended": bool(getattr(
                coord, "_persistence_suspended", False
            )),
            # v5.11.0 D1 — notify-dedup active key count.
            "notify_dedup_active_keys": notify_dedup_active_keys,
            # v5.11.0 D4 — boot-storm cache expiry.
            "boot_storm_cache_expires_iso": getattr(
                coord, "_boot_storm_cache_expires_iso", None
            ),
            # v5.11.0 D2 — shadow-accuracy sample count.
            "shadow_accuracy_samples_count": shadow_samples_count,
            # v5.11.0 D6 — promotion readiness per scorable dimension.
            "promotion_readiness": promotion_readiness,
        }


class OptimizerRoomHealthSensor(_OptimizerCMSensorBase):
    """sensor.ura_optimizer_room_health — worst room score + rooms map."""

    _attr_icon = "mdi:home-search"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_optimizer_room_health"
        self._attr_name = "Optimizer Room Health"
        self._attr_native_value = None

    @property
    def native_value(self):
        coord = self._get_coord()
        if coord is None or not coord._room_scores:
            return None
        return min(coord._room_scores.values())

    @property
    def extra_state_attributes(self) -> dict:
        coord = self._get_coord()
        if coord is None:
            return {"rooms": {}, "zones": {}}
        # v4.7.36 fix-up C-sensor: ``_zone_scores`` is populated when a
        # zone-level dimension fires (override_frequency, vacancy_management,
        # setpoint_compliance) but had no surface — expose it alongside
        # ``rooms`` so the operator can see zone-level health too.
        return {
            "rooms": dict(coord._room_scores),
            "zones": dict(getattr(coord, "_zone_scores", {}) or {}),
        }


class RoomOptimizationHealthSensor(UniversalRoomEntity, SensorEntity):
    """sensor.{room}_optimization_health — per-room health gauge.

    Lives on the Room device. Subscribes to
    SIGNAL_OPTIMIZER_FINDING_EMITTED to refresh on every new finding.
    Bug Class #50 + #5 safe — placeholder state until first cycle.
    """

    _attr_icon = "mdi:home-heart"
    _attr_should_poll = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        super().__init__(coordinator, "optimization_health",
                         "Optimization Health")
        self._signal_unsubs: list = []
        self._attr_native_value = None

    def _get_optimizer(self):
        manager = self.coordinator.hass.data.get(DOMAIN, {}).get(
            "coordinator_manager"
        )
        if manager is None:
            return None
        try:
            return manager.coordinators.get("optimization")
        except Exception:
            return None

    def _room_name(self) -> str:
        try:
            return self.coordinator.entry.data.get("room_name", "")
        except Exception:
            return ""

    @property
    def native_value(self):
        opt = self._get_optimizer()
        if opt is None:
            return None
        # v5.11.0 — per critique binding decision: return None until the
        # first cycle has completed (avoids Bug Class #5 fake defaults).
        if not getattr(opt, "_last_evaluation_iso", None):
            return None
        room = self._room_name()
        if not room:
            return None
        try:
            return opt.get_room_score(room)
        except Exception:
            return None

    @property
    def extra_state_attributes(self) -> dict:
        opt = self._get_optimizer()
        if opt is None:
            return {"degraded_dimensions": [], "worst_open": None}
        room = self._room_name()
        degraded: list[str] = []
        # v5.11.0 — worst_open: the highest-severity currently-open room
        # finding, so the operator can see the reason for a degraded
        # room-score at a glance.
        severity_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        worst_open: dict | None = None
        worst_rank = 0
        for f in opt._last_findings:
            if f.level == "room" and f.target_id == room:
                dim_str = str(f.dimension)
                if dim_str not in degraded and dim_str != "meta":
                    degraded.append(dim_str)
                # Skip META for worst_open — it's a liveness sentinel.
                if dim_str == "meta":
                    continue
                sev = (getattr(f, "severity", "low") or "low").lower()
                rank = severity_rank.get(sev, 0)
                if rank > worst_rank:
                    worst_rank = rank
                    worst_open = {
                        "dimension": dim_str,
                        "severity": sev,
                        "description": (f.description or "")[:255],
                    }
        return {
            "degraded_dimensions": degraded,
            "worst_open": worst_open,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_OPTIMIZER_FINDING_EMITTED

        @callback
        def _on_finding(_payload=None):
            self.async_write_ha_state()

        unsub = async_dispatcher_connect(
            self.coordinator.hass,
            SIGNAL_OPTIMIZER_FINDING_EMITTED,
            _on_finding,
        )
        self._signal_unsubs.append(unsub)
        self.async_on_remove(unsub)

    async def async_will_remove_from_hass(self) -> None:
        for u in list(self._signal_unsubs):
            try:
                u()
            except Exception:
                pass
        self._signal_unsubs.clear()
        await super().async_will_remove_from_hass()

"""Energy Coordinator — manages battery, pool, EV, TOU optimization, solar awareness.

Sub-Cycle E1: TOU Engine + Battery Strategy
Sub-Cycle E2: Pool + EV + Smart Plugs
Priority 40 (higher than HVAC at 30, lower than Safety at 100).
"""

from __future__ import annotations

import asyncio
import collections
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import async_track_time_interval

from .base import (
    BaseCoordinator,
    CoordinatorAction,
    Intent,
    ServiceCallAction,
    Severity,
)
from .energy_battery import BatteryStrategy
from .energy_billing import CostTracker
from .energy_circuits import GeneratorMonitor, SPANCircuitMonitor
from .energy_forecast import AccuracyTracker, DailyEnergyPredictor, RoomPowerProfile, get_time_bin
from .energy_pool import EVChargerController, PoolOptimizer, SmartPlugController
from ..const import DOMAIN as _DOMAIN  # v4.2.5: Module-level for lambda closures
from .energy_const import (
    CONF_ENERGY_ARBITRAGE_ENABLED,
    CONF_ENERGY_ARBITRAGE_SOC_TARGET,
    CONF_ENERGY_BATTERY_CAPACITY_ENTITY,
    CONF_ENERGY_BATTERY_POWER_ENTITY,
    CONF_ENERGY_BATTERY_SOC_ENTITY,
    CONF_ENERGY_CHARGE_FROM_GRID_ENTITY,
    CONF_ENERGY_CONSTRAINT_COAST_OFFSET,
    CONF_ENERGY_CONSTRAINT_PRECOOL_OFFSET,
    CONF_ENERGY_CONSTRAINT_PREHEAT_OFFSET,
    CONF_ENERGY_CONSTRAINT_SHED_OFFSET,
    CONF_ENERGY_CONSUMPTION_TODAY_ENTITY,
    CONF_ENERGY_EXCESS_SOLAR_ENABLED,
    CONF_ENERGY_EXCESS_SOLAR_KWH,
    CONF_ENERGY_EXCESS_SOLAR_SOC,
    CONF_ENERGY_GRID_IMPORT_CAP_ENABLED,
    CONF_ENERGY_GRID_IMPORT_CAP_KW,
    CONF_ENERGY_GRID_ENABLED_ENTITY,
    CONF_ENERGY_GRID_ENTITY,
    CONF_ENERGY_LIFETIME_BATTERY_CHARGED_ENTITY,
    CONF_ENERGY_LIFETIME_BATTERY_DISCHARGED_ENTITY,
    CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY,
    CONF_ENERGY_LIFETIME_NET_EXPORT_ENTITY,
    CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY,
    CONF_ENERGY_LIFETIME_PRODUCTION_ENTITY,
    CONF_ENERGY_LOAD_SHEDDING_ENABLED,
    CONF_ENERGY_LOAD_SHEDDING_MODE,
    CONF_ENERGY_LOAD_SHEDDING_SUSTAINED_MINUTES,
    CONF_ENERGY_LOAD_SHEDDING_THRESHOLD,
    CONF_ENERGY_NET_POWER_ENTITY,
    CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT,
    CONF_ENERGY_OFFPEAK_DRAIN_GOOD,
    CONF_ENERGY_OFFPEAK_DRAIN_MODERATE,
    CONF_ENERGY_OFFPEAK_DRAIN_POOR,
    CONF_ENERGY_PREHEAT_TEMP_THRESHOLD,
    CONF_ENERGY_RESERVE_SOC_ENTITY,
    CONF_ENERGY_SOLAR_ENTITY,
    CONF_ENERGY_SOLCAST_REMAINING_ENTITY,
    CONF_ENERGY_SOLCAST_TODAY_ENTITY,
    CONF_ENERGY_SOLCAST_TOMORROW_ENTITY,
    CONF_ENERGY_STORAGE_MODE_ENTITY,
    CONF_ENERGY_WEATHER_ENTITY,
    DEFAULT_ARBITRAGE_SOC_TARGET,
    DEFAULT_CONSTRAINT_COAST_OFFSET,
    DEFAULT_CONSTRAINT_PRECOOL_OFFSET,
    DEFAULT_CONSTRAINT_PREHEAT_OFFSET,
    DEFAULT_CONSTRAINT_SHED_OFFSET,
    DEFAULT_DECISION_INTERVAL_MINUTES,
    DEFAULT_EXCESS_SOLAR_KWH_THRESHOLD,
    DEFAULT_GRID_IMPORT_CAP_HYSTERESIS_KW,
    DEFAULT_GRID_IMPORT_CAP_KW,
    DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD,
    DEFAULT_LOAD_SHEDDING_SUSTAINED_MINUTES,
    DEFAULT_LOAD_SHEDDING_THRESHOLD_KW,
    DEFAULT_OFFPEAK_DRAIN_EXCELLENT,
    DEFAULT_OFFPEAK_DRAIN_GOOD,
    DEFAULT_OFFPEAK_DRAIN_MODERATE,
    DEFAULT_OFFPEAK_DRAIN_POOR,
    DEFAULT_PREHEAT_TEMP_THRESHOLD,
    DEFAULT_RESERVE_SOC,
    EVSE_CHARGING_POWER_THRESHOLD,
    LOAD_SHEDDING_AUTO_MIN_DAYS,
    LOAD_SHEDDING_AUTO_PERCENTILE,
    LOAD_SHEDDING_MODE_AUTO,
    LOAD_SHEDDING_MODE_FIXED,
    LOAD_SHEDDING_PRIORITY,
)
from .energy_tou import TOURateEngine
from .signals import (
    SIGNAL_OPTIMIZER_INTENT,
    SIGNAL_OPTIMIZER_INTENT_VETO,
    SIGNAL_SAFETY_HAZARD,
)

_LOGGER = logging.getLogger(__name__)


class EnergyCoordinator(BaseCoordinator):
    """Energy domain coordinator — TOU awareness, battery optimization, solar forecasting.

    Priority: 40 (above Comfort/HVAC at 20-30, below Safety at 100)
    Owns: Battery (Enphase), Pool (future E2), EVSEs (future E2), SPAN (future E3)
    Publishes: SIGNAL_ENERGY_CONSTRAINT (future E6) for HVAC coordinator
    """

    def __init__(
        self,
        hass: HomeAssistant,
        reserve_soc: int = DEFAULT_RESERVE_SOC,
        decision_interval: int = DEFAULT_DECISION_INTERVAL_MINUTES,
        entity_config: dict[str, str] | None = None,
        pool_speed_entity: str | None = None,
        evse_config: dict | None = None,
        smart_plug_entities: list[str] | None = None,
        plug_config: dict | None = None,
        solar_classification_mode: str = "automatic",
        custom_solar_thresholds: dict[str, float] | None = None,
        tou_engine: TOURateEngine | None = None,
    ) -> None:
        """Initialize Energy Coordinator."""
        super().__init__(
            hass,
            coordinator_id="energy",
            name="Energy Coordinator",
            priority=40,
        )
        self._decision_interval = decision_interval

        # v4.0.5: Accept pre-loaded TOU engine (async-loaded by __init__.py before EC init).
        # v4.6.8: sync from_json_file fallback removed — single install, always async path.
        if tou_engine is None:
            raise ValueError(
                "EnergyCoordinator requires a pre-loaded TOURateEngine (tou_engine=). "
                "Use TOURateEngine.async_from_json_file() in __init__.py before creating EC."
            )
        self._tou = tou_engine

        # Build off-peak drain targets from config
        ec = entity_config or {}
        # OC Phase 5 Pillar A: keep the raw entity_config map so the
        # sibling-handshake honor logic can resolve the battery-strategy
        # writeable entity ids without re-deriving them through battery /
        # strategy sub-components (which may be None when EC is disabled).
        self._entity_config: dict[str, str] = dict(ec)

        # v4.0.12: Resolved Envoy entity IDs (auto-derived or explicit config).
        # v4.3.1: no production fallback. B1 envoy validation gate (v4.2.29)
        # ensures these are populated when EC is enabled. Values may be None
        # for installs where EC is disabled or envoy validation skipped — all
        # downstream consumers must handle None gracefully via state.get(None)
        # short-circuit at the read site.
        self._entity_lifetime_consumption = ec.get(CONF_ENERGY_LIFETIME_CONSUMPTION_ENTITY)
        self._entity_lifetime_production = ec.get(CONF_ENERGY_LIFETIME_PRODUCTION_ENTITY)
        self._entity_lifetime_net_import = ec.get(CONF_ENERGY_LIFETIME_NET_IMPORT_ENTITY)
        self._entity_lifetime_net_export = ec.get(CONF_ENERGY_LIFETIME_NET_EXPORT_ENTITY)
        self._entity_lifetime_battery_charged = ec.get(CONF_ENERGY_LIFETIME_BATTERY_CHARGED_ENTITY)
        self._entity_lifetime_battery_discharged = ec.get(CONF_ENERGY_LIFETIME_BATTERY_DISCHARGED_ENTITY)
        self._entity_consumption_today = ec.get(CONF_ENERGY_CONSUMPTION_TODAY_ENTITY)
        self._entity_grid_consumption = ec.get(CONF_ENERGY_GRID_ENTITY)

        offpeak_drain_targets = {
            "excellent": ec.get(CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT, DEFAULT_OFFPEAK_DRAIN_EXCELLENT),
            "good": ec.get(CONF_ENERGY_OFFPEAK_DRAIN_GOOD, DEFAULT_OFFPEAK_DRAIN_GOOD),
            "moderate": ec.get(CONF_ENERGY_OFFPEAK_DRAIN_MODERATE, DEFAULT_OFFPEAK_DRAIN_MODERATE),
            "poor": ec.get(CONF_ENERGY_OFFPEAK_DRAIN_POOR, DEFAULT_OFFPEAK_DRAIN_POOR),
        }

        # v4.5.0 D1/D2: peak_buffer_target is the new live-tunable; falls
        # back to legacy arbitrage_soc_target during the migration window
        # (the rename migration in __init__.py copies the old key forward).
        # arbitrage_charge_lead_time_min is the new D2 number-box knob;
        # initial seed only — runtime store is RestoreEntity (per the
        # URA mirror pattern, see memory feedback_ura_mirror_pattern.md).
        from .energy_const import (
            CONF_ENERGY_PEAK_BUFFER_TARGET,
            CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW,
            CONF_ENERGY_MULTI_DAY_HORIZON_ENABLED,
            CONF_ENERGY_SOLCAST_DAY_3_ENTITY,
            DEFAULT_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
            DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW,
            DEFAULT_PEAK_BUFFER_TARGET,
        )
        peak_buffer_target = int(ec.get(
            CONF_ENERGY_PEAK_BUFFER_TARGET,
            ec.get(CONF_ENERGY_ARBITRAGE_SOC_TARGET, DEFAULT_PEAK_BUFFER_TARGET),
        ))
        lead_time = int(ec.get(
            CONF_ENERGY_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
            DEFAULT_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
        ))
        grid_import_guard_kw = float(ec.get(
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW,
            DEFAULT_ARBITRAGE_GRID_IMPORT_GUARD_KW,
        ))
        self._battery = BatteryStrategy(
            hass,
            reserve_soc=reserve_soc,
            entity_config=self._build_entity_map(entity_config),
            solar_classification_mode=solar_classification_mode,
            custom_solar_thresholds=custom_solar_thresholds,
            offpeak_drain_targets=offpeak_drain_targets,
            arbitrage_enabled=ec.get(CONF_ENERGY_ARBITRAGE_ENABLED, False),
            arbitrage_soc_target=ec.get(
                CONF_ENERGY_ARBITRAGE_SOC_TARGET, DEFAULT_ARBITRAGE_SOC_TARGET
            ),
            peak_buffer_target=peak_buffer_target,
            arbitrage_charge_lead_time_min=lead_time,
            arbitrage_grid_import_guard_kw=grid_import_guard_kw,
            tou_engine=self._tou,  # v4.5.0 D8: charge-window math
            multi_day_horizon_enabled=ec.get(
                CONF_ENERGY_MULTI_DAY_HORIZON_ENABLED, False
            ),
            solcast_day_3_entity=ec.get(CONF_ENERGY_SOLCAST_DAY_3_ENTITY),
        )
        # E2: Pool, EV, Smart Plugs
        self._pool = PoolOptimizer(hass, pool_speed_entity=pool_speed_entity)
        self._ev = EVChargerController(hass, evse_config=evse_config)
        self._smart_plugs = SmartPlugController(
            hass,
            plug_entities=smart_plug_entities,
            plug_config=plug_config,
        )

        # v3.11.0: Configured weather entity (for DB logging).
        # v4.7.x Cycle A: _weather_entity is the fallback when WeatherProviderManager
        # is not yet set up. At runtime, _get_active_weather_entity() resolves via
        # the manager first, falling back here. See A4 migration note.
        from .energy_const import DEFAULT_WEATHER_ENTITY
        self._weather_entity: str = ec.get(CONF_ENERGY_WEATHER_ENTITY, DEFAULT_WEATHER_ENTITY)

        # v3.11.0: Excess solar EVSE config
        self._excess_solar_enabled: bool = ec.get(CONF_ENERGY_EXCESS_SOLAR_ENABLED, False)
        self._excess_solar_soc: int = ec.get(
            CONF_ENERGY_EXCESS_SOLAR_SOC, DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD
        )
        self._excess_solar_kwh: float = ec.get(
            CONF_ENERGY_EXCESS_SOLAR_KWH, DEFAULT_EXCESS_SOLAR_KWH_THRESHOLD
        )
        self._evse_battery_hold_active: bool = False
        self._evse_hold_soc: int | None = None  # Captured SOC at start of EVSE hold

        # v4.0.18: EV grid import cap
        self._grid_import_cap_enabled: bool = ec.get(
            CONF_ENERGY_GRID_IMPORT_CAP_ENABLED, False)
        self._grid_import_cap_kw: float = float(ec.get(
            CONF_ENERGY_GRID_IMPORT_CAP_KW, DEFAULT_GRID_IMPORT_CAP_KW))

        # v4.2.10: EV TOU management toggle (was always-on)
        self._ev_tou_enabled: bool = True

        # v4.2.17: EV battery drain protection
        from .energy_const import (
            DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD,
            CONF_ENERGY_EV_BATTERY_DRAIN_SOC,
        )
        self._ev_battery_drain_soc: int = int(ec.get(
            CONF_ENERGY_EV_BATTERY_DRAIN_SOC,
            DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD))

        # v4.7.6 D2/D3.2: EV fill-priority pause SOC threshold (runtime-tunable
        # via number.ura_energy_coordinator_fill_priority_soc). Seeded from
        # entry.options on first install; RestoreEntity is canonical thereafter.
        from .energy_const import (
            CONF_ENERGY_FILL_PRIORITY_SOC,
            DEFAULT_FILL_PRIORITY_SOC,
        )
        self._fill_priority_soc: int = int(ec.get(
            CONF_ENERGY_FILL_PRIORITY_SOC,
            DEFAULT_FILL_PRIORITY_SOC,
        ))

        # v4.7.6 D4: edge-detection state for "first fill-priority pause per day"
        # NM trip. Tracks previous-tick non-empty state.
        self._fill_priority_was_empty: bool = True
        # ISO date string (YYYY-MM-DD) of the day we last fired the NM trip;
        # resets implicitly at midnight when the date string changes.
        self._fill_priority_nm_trip_date: str | None = None

        # E3: Circuit monitoring + generator
        # v4.2.0: Configurable circuit sources
        from .energy_const import (
            CONF_ENERGY_CIRCUIT_EXTRA_ENTITIES,
            CONF_ENERGY_CIRCUIT_EXCLUDE_ENTITIES,
            CONF_ENERGY_CIRCUIT_AUTODISCOVER_SPAN,
            CONF_ENERGY_GENERATOR_ENTITY,
        )
        self._circuits = SPANCircuitMonitor(
            hass,
            extra_entities=ec.get(CONF_ENERGY_CIRCUIT_EXTRA_ENTITIES, []),
            exclude_entities=ec.get(CONF_ENERGY_CIRCUIT_EXCLUDE_ENTITIES, []),
            autodiscover_span=ec.get(CONF_ENERGY_CIRCUIT_AUTODISCOVER_SPAN, True),
        )
        generator_entity = ec.get(CONF_ENERGY_GENERATOR_ENTITY)
        self._generator = GeneratorMonitor(
            hass, status_entity=generator_entity
        ) if generator_entity else GeneratorMonitor(hass)

        # E4: Billing + cost tracking
        # v4.2.0: Optional direct grid import/export sensors (Emporia mains)
        from .energy_const import (
            CONF_ENERGY_GRID_IMPORT_ENTITY,
            CONF_ENERGY_GRID_EXPORT_ENTITY,
            CONF_ENERGY_UTILITY_METER_ENTITY,
        )
        self._grid_import_entity: str | None = ec.get(CONF_ENERGY_GRID_IMPORT_ENTITY)
        self._utility_meter_entity: str | None = ec.get(CONF_ENERGY_UTILITY_METER_ENTITY)
        self._billing = CostTracker(
            hass, self._tou,
            net_power_entity=ec.get(CONF_ENERGY_NET_POWER_ENTITY),
            solar_entity=ec.get(CONF_ENERGY_SOLAR_ENTITY),
            grid_import_entity=ec.get(CONF_ENERGY_GRID_IMPORT_ENTITY),
            grid_export_entity=ec.get(CONF_ENERGY_GRID_EXPORT_ENTITY),
        )

        # E5: Forecasting + prediction
        # v4.1.1 B4 L2: Room power profiles + occupancy weighting
        self._power_profiles = RoomPowerProfile()
        # Runtime toggle — init from config, overridable by switch entity
        self._occupancy_weighted = ec.get("occupancy_weighted_energy", False)
        self._room_ids = self._collect_room_ids()

        weather_ent = (entity_config or {}).get(CONF_ENERGY_WEATHER_ENTITY)
        self._predictor = DailyEnergyPredictor(
            hass,
            battery_soc_entity=ec.get(CONF_ENERGY_BATTERY_SOC_ENTITY),
            weather_entity=weather_ent,
            battery_capacity_entity=ec.get(CONF_ENERGY_BATTERY_CAPACITY_ENTITY),
            # v4.1.1: Lazy lookup — survives integration reloads
            bayesian_predictor=lambda: hass.data.get(_DOMAIN, {}).get("bayesian_predictor"),
            power_profiles=self._power_profiles,
            room_ids=self._room_ids,
            occupancy_enabled_fn=lambda: self._occupancy_weighted,
        )
        self._accuracy = AccuracyTracker()

        # Hold cache for battery_full_time (survives brief Envoy outages)
        self._last_battery_full_time: str | None = None

        # v4.3.0 D4: Arbitrage cycle accounting state. Tracks SOC at the start
        # of the current arbitrage segment so each decision tick can compute
        # the kWh delta and persist a cycle row. None when arbitrage is inactive.
        self._arbitrage_prev_soc: float | None = None
        # Cached rollup refreshed each tick after cycle accounting; sensors
        # read from this synchronously. Empty until first refresh.
        self._arbitrage_status_cache: dict[str, Any] = {}

        # E6: HVAC constraints + covers
        self._hvac_constraint_mode: str = "normal"
        self._hvac_constraint_offset: float = 0.0
        self._hvac_constraint_reason: str = ""
        self._last_published_constraint: str = ""  # track to avoid duplicate signals
        self._energy_situation: str = "normal"
        # E6 v3.9.0: Load shedding + configurable constraints
        # (ec already assigned above)
        self._load_shedding_enabled: bool = ec.get(
            CONF_ENERGY_LOAD_SHEDDING_ENABLED, False
        )
        self._load_shedding_threshold_kw: float = ec.get(
            CONF_ENERGY_LOAD_SHEDDING_THRESHOLD, DEFAULT_LOAD_SHEDDING_THRESHOLD_KW
        )
        self._load_shedding_sustained_minutes: int = ec.get(
            CONF_ENERGY_LOAD_SHEDDING_SUSTAINED_MINUTES, DEFAULT_LOAD_SHEDDING_SUSTAINED_MINUTES
        )
        self._load_shedding_mode: str = ec.get(
            CONF_ENERGY_LOAD_SHEDDING_MODE, LOAD_SHEDDING_MODE_FIXED
        )
        self._constraint_coast_offset: float = ec.get(
            CONF_ENERGY_CONSTRAINT_COAST_OFFSET, DEFAULT_CONSTRAINT_COAST_OFFSET
        )
        self._constraint_precool_offset: float = ec.get(
            CONF_ENERGY_CONSTRAINT_PRECOOL_OFFSET, DEFAULT_CONSTRAINT_PRECOOL_OFFSET
        )
        self._constraint_preheat_offset: float = ec.get(
            CONF_ENERGY_CONSTRAINT_PREHEAT_OFFSET, DEFAULT_CONSTRAINT_PREHEAT_OFFSET
        )
        self._constraint_shed_offset: float = ec.get(
            CONF_ENERGY_CONSTRAINT_SHED_OFFSET, DEFAULT_CONSTRAINT_SHED_OFFSET
        )
        self._preheat_temp_threshold: float = ec.get(
            CONF_ENERGY_PREHEAT_TEMP_THRESHOLD, DEFAULT_PREHEAT_TEMP_THRESHOLD
        )
        # Load shedding state tracking
        self._sustained_import_readings: list[float] = []
        self._load_shedding_active_level: int = 0  # 0=none, 1-4=cascade level
        self._learned_threshold_kw: float | None = None  # auto-learned from history
        self._peak_import_history: list[float] = []  # for learning
        self._load_shedding_grace_cycles: int = 0  # suppress de-escalation after restore

        self._decision_timer_unsub = None

        # Observation mode: sensors compute, no actions executed
        self._observation_mode: bool = False

        # OC Phase 5 Pillar A handshake — unsub for SIGNAL_OPTIMIZER_INTENT.
        # Stored separately so async_setup can detect re-entry (options reload)
        # and skip a double-subscribe; also appended to ``_unsub_listeners``
        # so BaseCoordinator.async_teardown clears it (Bug Class #50 / #19).
        self._optimizer_intent_unsub = None
        # Reason string for the most recent ``honor_optimizer_intent`` veto.
        # Read by ``_on_optimizer_intent`` immediately after evaluation so a
        # concurrent intent can't race us — the value is reset at the top of
        # every honor call, so reads are valid only inside the same callback.
        self._last_veto_reason: str | None = None

        # v4.7.x D2 fix-up H1 + boot-decoupling C7 fix: track sub-switch
        # deferred-restore convergence DYNAMICALLY.  The counter starts at
        # 0 and is incremented by each registering switch via
        # register_sub_switch_for_restore_accounting() at construction time
        # (called from the factory body and HVACDynamicPresetSwitch.__init__).
        # This replaces the prior hardcoded 6, which was stale (real
        # population is 8: 7 factory EC sub-switches + HVACDynamicPresetSwitch)
        # and would early-converge ECSubSwitchesSyncedSensor and mask a
        # genuinely stuck switch.
        self._pending_sub_switch_restores: int = 0
        # Track which switches have registered so reload-resets don't
        # double-count.  Key = unique_suffix string supplied by the caller.
        self._registered_sub_switches: set[str] = set()

        # State tracking
        self._last_battery_decision: dict[str, Any] = {}
        self._tou_transition_count: int = 0
        self._last_reset_date: str = ""
        self._cycle_count: int = 0  # v3.11.0: for throttling DB writes

        # Envoy lifetime consumption snapshot for accurate daily tracking.
        # At each date change, delta = current - snapshot = true daily consumption.
        # Uses Envoy's consumption CT (includes grid + solar self-consumed + battery).
        self._lifetime_consumption_snapshot: float | None = None

        # v3.14.0: Additional lifetime snapshots for derived consumption.
        # With net-consumption CT, lifetime_energy_consumption = net grid import only.
        # True consumption = grid_import + solar_self_consumed + net_battery_discharge.
        self._lifetime_production_snapshot: float | None = None
        self._lifetime_net_import_snapshot: float | None = None
        self._lifetime_net_export_snapshot: float | None = None
        self._lifetime_battery_charged_snapshot: float | None = None
        self._lifetime_battery_discharged_snapshot: float | None = None

        # Cached forecast temps (updated each decision cycle via async service)
        self._cached_forecast_high: float | None = None
        self._cached_forecast_low: float | None = None
        # v4.7.x Cycle A: apparent-temp forecast high from WeatherProviderManager
        self._cached_apparent_forecast_high: float | None = None

        # v4.7.1 Cycle B: Dynamic Preset Override Source
        # Master enable — seeded from CM options; runtime-tunable via switch
        from .energy_const import CONF_DYNAMIC_PRESET_ENABLED, DEFAULT_DYNAMIC_PRESET_ENABLED
        self._dynamic_preset_enabled: bool = ec.get(
            CONF_DYNAMIC_PRESET_ENABLED, DEFAULT_DYNAMIC_PRESET_ENABLED
        )
        # Solar HVAC Banking master enable (EC sub-switch). Seeded from CM
        # options; runtime-tunable via the "Solar HVAC Banking" switch on
        # the EC device. HVACPredictor reads this via _is_solar_banking_enabled()
        # to short-circuit the banking branch in _check_pre_conditioning.
        # See PLANNING_solar_banking_toggle.md (D3).
        from .hvac_const import (
            CONF_HVAC_SOLAR_BANK_ENABLED,
            DEFAULT_HVAC_SOLAR_BANK_ENABLED,
        )
        self._solar_banking_enabled: bool = bool(ec.get(
            CONF_HVAC_SOLAR_BANK_ENABLED, DEFAULT_HVAC_SOLAR_BANK_ENABLED
        ))
        # Lazily instantiated on first evaluate call (avoids circular import at __init__).
        self._dynamic_preset_source: Any = None
        # Accumulated overrides per zone from the most recent evaluate call.
        # Key: zone_id, Value: list[PresetOverride]
        self._dynamic_preset_overrides: dict[str, list] = {}
        # v4.7.7 B2: skip_reason per zone from the most recent evaluate call.
        # Populated when overrides is empty for that zone; missing key means
        # the zone produced overrides (no skip).
        # Allowed reasons: see canonical `DPM_SKIP_REASONS` frozenset in
        # energy_const.py (single source of truth — fix-up B-H2 v4.7.17.2).
        # Read by DynamicPresetOverridesAppliedSensor.extra_state_attributes
        # to expose the per-zone reason on the existing skipped_zones attr.
        self._dynamic_preset_skip_reasons: dict[str, str] = {}
        # v4.7.9 D2: previous-tick snapshot of skip_reasons for the new
        # SIGNAL_DPM_SKIP_REASONS_UPDATED edge detection. Init to {} so the
        # first tick against an empty reasons dict does NOT spuriously fire.
        # First tick with non-empty reasons WILL fire (correct — real state
        # change from "no signal yet" to "first reason").
        self._dynamic_preset_skip_reasons_prev: dict[str, str] = {}

        # Envoy availability tracking
        self._envoy_unavailable_count: int = 0
        self._envoy_last_available: str | None = None
        # EC Envoy boot-decoupling D7: degraded observability.
        # `_envoy_degraded` is True while the per-cycle envoy read is
        # unavailable (critical envoy entities missing/unavailable this
        # cycle); `_envoy_degraded_since` is the ISO timestamp at which
        # the current degraded streak began (None when not degraded).
        # Surfaced as attributes on sensor.ura_energy_envoy_status.
        self._envoy_degraded: bool = False
        self._envoy_degraded_since: str | None = None
        # v4.3.0 D6: timestamp of most recent cross-check data anomaly. When
        # set within the last hour, EnvoyStatusSensor reports "stale" even
        # though state objects look fresh — covers the v4.2.28 latent defect
        # where envoy_status said "online" while data was zeroed/wrong after
        # an Envoy reboot.
        self._envoy_data_anomaly_at: str | None = None
        # Cross-check: last logged divergence (avoid log spam)
        self._last_crosscheck_hour: int = -1
        # Throttle peak import DB saves to once per hour
        # v4.2.6: Initialize to current hour to defer first-cycle write (was -1)
        from homeassistant.util import dt as _dt_util
        _current_hour = _dt_util.now().hour
        self._last_peak_save_hour: int = _current_hour
        self._last_profile_save_hour: int = _current_hour
        self._peak_import_dirty: bool = False

        # v3.13.2+: MetricBaselines for learned anomaly detection
        from .coordinator_diagnostics import MetricBaseline
        # Load shedding: cap at 1500 samples (~30 days of peak data) for recency
        self._peak_import_baseline: MetricBaseline = MetricBaseline(
            metric_name="peak_import_kw",
            coordinator_id="energy",
            scope="load_shedding",
            max_samples=1500,
        )
        # v3.13.3: Additional EC baselines
        self._soc_at_peak_baseline: MetricBaseline = MetricBaseline(
            metric_name="soc_at_peak_start",
            coordinator_id="energy",
            scope="battery",
            max_samples=365,  # ~1 year of daily readings
        )
        self._daily_import_cost_baseline: MetricBaseline = MetricBaseline(
            metric_name="daily_import_cost",
            coordinator_id="energy",
            scope="billing",
            max_samples=365,
        )
        self._solar_forecast_error_baseline: MetricBaseline = MetricBaseline(
            metric_name="solar_forecast_error_pct",
            coordinator_id="energy",
            scope="forecast",
            max_samples=365,
        )

        # v4.6.9 D3: Decision stream ring buffer — capped at 20 entries.
        # Bug Class #25 (bounded list): deque(maxlen=20) enforces the hard cap.
        # Each entry: { timestamp_iso, action, reason, tou_period, target_entity }
        self._decision_buffer: collections.deque = collections.deque(maxlen=20)

    # ------------------------------------------------------------------
    # v4.6.9 D3: Decision stream helpers
    # ------------------------------------------------------------------

    def _record_decision(
        self,
        action: str,
        reason: str,
        target_entity: str | None = None,
    ) -> None:
        """Append a decision entry to the ring buffer.

        **Threading contract** (Tier 2-DB Reviewer A H1): MUST be called from
        the HA event loop. Do NOT invoke from a thread executor — deque mutation
        is safe under CPython's GIL but `get_recent_decisions()` snapshots via
        `list(buffer)` and a concurrent appender from a thread could observe
        a partial view. All current callers are event-loop-bound; future
        sensor platforms must follow the same constraint.

        Bug Class #11: timestamp is UTC ISO 8601 string, never a datetime obj.
        Bug Class #22: tou_period is read directly from TOURateEngine._VALID_PERIODS
                       vocabulary (peak | mid_peak | off_peak).
        Bug Class #25: deque(maxlen=20) enforces hard cap — no list growth.
        """
        from homeassistant.util import dt as dt_util
        try:
            tou_period: str = self._tou.get_current_period()
        except Exception:
            tou_period = "off_peak"
        entry: dict[str, Any] = {
            "timestamp_iso": dt_util.utcnow().isoformat(),
            "action": action,
            "reason": reason,
            "tou_period": tou_period,
            "target_entity": target_entity,
        }
        self._decision_buffer.append(entry)
        _LOGGER.debug(
            "Energy decision recorded: action=%s reason=%s tou_period=%s target=%s",
            action, reason, tou_period, target_entity,
        )

    def get_recent_decisions(self) -> dict[str, Any]:
        """Return decision stream data for the sensor.

        Returns a dict with:
          - decisions: list[dict] — last 20 decisions, newest first
          - count_24h: int — number of decisions in the last 24h
          - last_action_at_iso: str | None — timestamp of most recent entry

        Bug Class #29: covers empty-buffer branch (count_24h=0, empty list).
        Bug Class #37: stable shape — all three keys always present.
        """
        # Tier 2-DB Reviewer A H2 fix: imports at function top, not loop body.
        from datetime import datetime, timedelta, timezone

        from homeassistant.util import dt as dt_util

        all_entries = list(self._decision_buffer)  # oldest→newest
        newest_first = list(reversed(all_entries))

        if not newest_first:
            return {
                "decisions": [],
                "count_24h": 0,
                "last_action_at_iso": None,
            }

        cutoff = dt_util.utcnow() - timedelta(hours=24)
        count_24h = 0
        for entry in all_entries:
            try:
                ts = datetime.fromisoformat(entry["timestamp_iso"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    count_24h += 1
            except Exception:
                pass

        last_action_at_iso: str | None = newest_first[0].get("timestamp_iso") if newest_first else None

        return {
            "decisions": newest_first,
            "count_24h": count_24h,
            "last_action_at_iso": last_action_at_iso,
        }

    def _build_entity_map(self, config: dict[str, str] | None) -> dict[str, str]:
        """Build entity mapping from config keys to battery strategy keys."""
        if not config:
            return {}
        key_map = {
            CONF_ENERGY_SOLAR_ENTITY: "solar_production",
            CONF_ENERGY_GRID_ENTITY: "grid_consumption",
            CONF_ENERGY_BATTERY_SOC_ENTITY: "battery_soc",
            CONF_ENERGY_BATTERY_POWER_ENTITY: "battery_power",
            CONF_ENERGY_BATTERY_CAPACITY_ENTITY: "battery_capacity",
            CONF_ENERGY_NET_POWER_ENTITY: "net_power",
            CONF_ENERGY_STORAGE_MODE_ENTITY: "storage_mode",
            CONF_ENERGY_RESERVE_SOC_ENTITY: "reserve_soc_number",
            CONF_ENERGY_GRID_ENABLED_ENTITY: "grid_enabled",
            CONF_ENERGY_CHARGE_FROM_GRID_ENTITY: "charge_from_grid",
            CONF_ENERGY_SOLCAST_TODAY_ENTITY: "solcast_today",
            CONF_ENERGY_SOLCAST_REMAINING_ENTITY: "solcast_remaining",
            CONF_ENERGY_SOLCAST_TOMORROW_ENTITY: "solcast_tomorrow",
            CONF_ENERGY_WEATHER_ENTITY: "weather",
        }
        result = {}
        for conf_key, strategy_key in key_map.items():
            if conf_key in config:
                result[strategy_key] = config[conf_key]
        return result

    async def async_setup(self) -> None:
        """Set up the energy coordinator — start decision timer."""
        from datetime import timedelta
        from homeassistant.util import dt as dt_util

        # Cancel existing timer if re-entering (disable/enable cycle)
        if self._decision_timer_unsub is not None:
            self._decision_timer_unsub()
            self._decision_timer_unsub = None

        # v3.21.0 D1: Sequential DB restore with 15s timeout
        # Review fix: keep sequential (avoids concurrent DB/shared-state contention)
        # but add timeout so locked DB doesn't hang coordinator startup
        now = dt_util.now()
        try:
            await asyncio.wait_for(
                self._restore_all_sequential(now), timeout=15.0
            )
        except asyncio.TimeoutError:
            _LOGGER.error(
                "Energy DB restore timed out after 15s — starting with defaults"
            )

        # Start periodic decision cycle
        self._decision_timer_unsub = async_track_time_interval(
            self.hass,
            self._async_decision_cycle,
            timedelta(minutes=self._decision_interval),
        )
        # Timer managed separately via _decision_timer_unsub — do NOT add to
        # _unsub_listeners to avoid double-unsubscribe in async_teardown

        # v3.22.0 D2: Subscribe to safety hazard signals
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SAFETY_HAZARD,
                self._handle_safety_hazard,
            )
        )

        # OC Phase 5 Pillar A: subscribe to SIGNAL_OPTIMIZER_INTENT so this
        # coordinator gets a chance to veto an Optimizer-proposed actuation
        # before it dispatches. Bug Class #50 guardrail — store the unsub on
        # ``_unsub_listeners`` and guard against double-subscribe on re-setup.
        if self._optimizer_intent_unsub is None:
            self._optimizer_intent_unsub = async_dispatcher_connect(
                self.hass,
                SIGNAL_OPTIMIZER_INTENT,
                self._on_optimizer_intent,
            )
            self._unsub_listeners.append(self._optimizer_intent_unsub)

        # Run initial evaluation
        await self._async_decision_cycle()

        _LOGGER.info(
            "Energy Coordinator started (interval=%dmin, reserve=%d%%)",
            self._decision_interval,
            self._battery.reserve_soc,
        )

        # v4.7.x D2: signal EC-ready so sub-switches can complete deferred
        # restore if the timer-based retry chain was exhausted before this
        # point.  Mirrors SIGNAL_NM_READY / SIGNAL_BAYESIAN_READY pattern.
        try:
            from homeassistant.helpers.dispatcher import async_dispatcher_send
            from .signals import SIGNAL_ENERGY_COORDINATOR_READY
            async_dispatcher_send(self.hass, SIGNAL_ENERGY_COORDINATOR_READY)
            _LOGGER.debug("SIGNAL_ENERGY_COORDINATOR_READY dispatched")
        except Exception:
            _LOGGER.debug(
                "SIGNAL_ENERGY_COORDINATOR_READY dispatch failed (non-fatal)",
                exc_info=True,
            )

    async def evaluate(
        self,
        intents: list[Intent],
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Evaluate intents and return battery/energy actions.

        The Energy Coordinator primarily runs on its own timer, but also
        responds to broadcast intents (e.g., house state changes).
        """
        actions: list[CoordinatorAction] = []

        # Check for TOU period transition
        new_period = self._tou.check_period_transition()
        if new_period is not None:
            self._tou_transition_count += 1
            _LOGGER.info("TOU transition detected: now %s", new_period)
            # Re-evaluate battery on TOU transition
            battery_actions = await self._evaluate_battery()
            actions.extend(battery_actions)

        return actions

    # ------------------------------------------------------------------
    # v3.22.0 D2: Safety hazard signal handler
    # ------------------------------------------------------------------

    @callback
    def _handle_safety_hazard(self, hazard: Any) -> None:
        """Handle safety hazard signal — trigger emergency load shed on critical.

        v3.22.0 D2: Cross-coordinator response to SIGNAL_SAFETY_HAZARD.
        Gated by CONF_ENERGY_ON_HAZARD_SHED_LOADS config toggle.
        Sets _load_shedding_active_level to max (all tiers shed).
        """
        if not self._enabled:
            return
        if self._observation_mode:
            _LOGGER.debug("Energy: Safety hazard received — suppressed by observation mode")
            return

        # Extract hazard fields with safe defaults
        if hazard is None:
            return
        if isinstance(hazard, dict):
            severity = hazard.get("severity", "")
            hazard_type = hazard.get("hazard_type", "")
        elif hasattr(hazard, "severity"):
            severity = getattr(hazard, "severity", "")
            hazard_type = getattr(hazard, "hazard_type", "")
        else:
            return

        if severity != "critical":
            return

        from ..const import CONF_ENERGY_ON_HAZARD_SHED_LOADS

        if self._get_signal_config(CONF_ENERGY_ON_HAZARD_SHED_LOADS):
            max_level = len(LOAD_SHEDDING_PRIORITY)
            _LOGGER.warning(
                "Energy: Safety hazard %s/%s — emergency load shed to level %d",
                hazard_type, severity, max_level,
            )
            # Set to max level — all load categories shed
            old_level = self._load_shedding_active_level
            self._load_shedding_active_level = max_level
            # Execute shed actions for any levels not already active
            for level_idx in range(old_level, max_level):
                target = LOAD_SHEDDING_PRIORITY[level_idx]
                self._execute_shed_action(target, activate=True)
        else:
            _LOGGER.info(
                "Energy: Safety hazard %s/%s — would trigger emergency load shed "
                "(disabled by config)",
                hazard_type, severity,
            )

    async def _restore_all_sequential(self, now) -> None:
        """Run all DB restore methods sequentially.

        v3.21.0: Wrapped by asyncio.wait_for(timeout=15) in async_setup().
        Sequential to avoid concurrent DB access and shared-state contention.
        Each method has its own try/except so one failure doesn't block others.
        """
        await self._restore_cycle_from_db(now)
        await self._restore_accuracy_from_db()
        await self._restore_peak_import_history()
        await self._fit_temp_regression()
        await self._restore_evse_state()
        await self._restore_circuit_state()
        await self._restore_energy_baselines()
        await self._restore_consumption_history()
        await self._restore_power_profiles()
        await self._restore_midnight_snapshot()
        await self._restore_envoy_cache()
        await self._restore_load_shedding_level()

    async def _restore_cycle_from_db(self, now) -> None:
        """Restore billing cycle totals from DB on startup."""
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        cycle_start = self._billing._get_cycle_start(now).isoformat()
        cycle_end = now.date().isoformat()
        try:
            cycle_data = await db.get_energy_daily_for_cycle(cycle_start, cycle_end)
            self._billing.update_from_db(cycle_data)
        except Exception as e:
            _LOGGER.warning("Could not restore billing cycle from DB: %s", e)

    async def _restore_accuracy_from_db(self) -> None:
        """Restore forecast accuracy history from DB on startup.

        Filters out rows with implausible consumption (< 10 kWh) which
        are artifacts of the net-consumption CT bug (pre-v3.14.0).
        """
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            rows = await db.get_energy_daily_recent(days=30)
            if rows:
                clean_rows = [
                    r for r in rows
                    if r.get("consumption_kwh") is not None
                    and r["consumption_kwh"] >= 10.0
                ]
                if clean_rows:
                    self._accuracy.restore_from_db(clean_rows)
                    self._predictor._adjustment_factor = (
                        self._accuracy.get_adjustment_factor()
                    )
                if len(clean_rows) < len(rows):
                    _LOGGER.info(
                        "Filtered %d implausible energy_daily rows (consumption < 10 kWh)",
                        len(rows) - len(clean_rows),
                    )
        except Exception as e:
            _LOGGER.warning("Could not restore accuracy from DB: %s", e)

    async def _restore_peak_import_history(self) -> None:
        """Restore peak import readings from DB.

        The learned threshold is recomputed from readings on the first
        decision cycle, so only the raw readings need restoration.
        """
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            readings = await db.get_peak_import_history()
            if readings:
                self._peak_import_history = readings
                _LOGGER.info(
                    "Restored %d peak import readings from DB", len(readings),
                )
        except Exception as e:
            _LOGGER.warning("Could not restore peak import history from DB: %s", e)

    async def _save_peak_import_history(self) -> None:
        """Persist peak import readings to DB."""
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            await db.save_peak_import_history(self._peak_import_history)
        except Exception as e:
            _LOGGER.warning("Could not save peak import history to DB: %s", e)

    async def _restore_evse_state(self) -> None:
        """Restore EVSE paused/excess-solar state from DB after restart.

        v<next> WS1 D1.1-D1.4:
        - Adds 10h staleness guard on both `evse_state` rows and the KV reads
          (rows older than 10h are skipped — Bug Class #10 bounded).
        - Restores three new KV keys: `ev_force_charge_until` (canonical
          force-charge expiry, parsed via `dt_util.parse_datetime` — Bug
          Class #13/#21), `evse_fill_priority_paused`, `evse_arbitrage_paused`,
          and the new `evse_proactive_offpeak_holds` intent-state set.
        - Switch RestoreEntity path (`switch.py:802-854`) remains a fast-path
          for entity-attribute round-trip; on conflict the KV value wins
          (KV is canonical) — runs AFTER the existing pause-set restores so
          observation-mode bookkeeping isn't disturbed.
        """
        from homeassistant.util import dt as dt_util
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            # 10h staleness guard — bounds restored intent vs a multi-day outage
            STALE_MAX_AGE_HOURS = 10.0
            states = await db.restore_evse_state(max_age_hours=STALE_MAX_AGE_HOURS)
            valid_evse_ids = set(self._ev._evse.keys())
            for evse_id, state in states.items():
                if evse_id not in valid_evse_ids:
                    _LOGGER.debug(
                        "Skipping stale EVSE ID from DB restore: %s", evse_id
                    )
                    continue
                if state.get("paused_by_energy"):
                    self._ev._paused_by_us.add(evse_id)
                if state.get("excess_solar_active"):
                    self._ev._excess_solar_active.add(evse_id)
            # Restore grid cap + battery drain state from key-value store.
            # v<next> WS1: all KV reads now route through the age-aware DAO
            # so a stale row from yesterday can't seed today's intent.
            # F3 (review): grid_cap/drain sets are re-derived from live
            # inputs every tick (`determine_actions` / `_update_battery_drain`
            # / grid-cap evaluation), so the 10h staleness gate here is
            # defense-in-depth (safe — fresh inputs overwrite within one
            # decision cycle even if staleness gating let a stale row leak).
            import json as _json
            grid_cap_json = await db.restore_energy_state_with_age(
                "evse_grid_cap_paused", max_age_hours=STALE_MAX_AGE_HOURS,
            )
            if grid_cap_json:
                try:
                    for eid in _json.loads(grid_cap_json):
                        if eid in valid_evse_ids:
                            self._ev._paused_by_grid_cap.add(eid)
                except (ValueError, TypeError):
                    pass
            # v4.2.17: Restore battery drain state
            drain_json = await db.restore_energy_state_with_age(
                "evse_battery_drain_paused", max_age_hours=STALE_MAX_AGE_HOURS,
            )
            if drain_json:
                try:
                    for eid in _json.loads(drain_json):
                        if eid in valid_evse_ids:
                            self._ev._paused_by_battery_drain.add(eid)
                except (ValueError, TypeError):
                    pass
            # v<next> WS1 D1.2: Restore fill-priority pause set
            fp_json = await db.restore_energy_state_with_age(
                "evse_fill_priority_paused", max_age_hours=STALE_MAX_AGE_HOURS,
            )
            if fp_json:
                try:
                    for eid in _json.loads(fp_json):
                        if eid in valid_evse_ids:
                            self._ev._paused_by_fill_priority.add(eid)
                except (ValueError, TypeError):
                    pass
            # v<next> WS1 D1.3b (operator decision 4): Restore arbitrage pause
            # set for symmetry with the other guard sets.
            arb_json = await db.restore_energy_state_with_age(
                "evse_arbitrage_paused", max_age_hours=STALE_MAX_AGE_HOURS,
            )
            if arb_json:
                try:
                    for eid in _json.loads(arb_json):
                        if eid in valid_evse_ids:
                            self._ev._paused_by_arbitrage.add(eid)
                except (ValueError, TypeError):
                    pass
            # v<next> WS1 D1.3: Restore proactive off-peak hold intent-state
            holds_json = await db.restore_energy_state_with_age(
                "evse_proactive_offpeak_holds", max_age_hours=STALE_MAX_AGE_HOURS,
            )
            if holds_json:
                try:
                    for eid in _json.loads(holds_json):
                        if eid in valid_evse_ids:
                            self._ev._proactive_offpeak_holds.add(eid)
                except (ValueError, TypeError):
                    pass
            # v<next> WS1 D1.1: Restore force-charge expiry from canonical KV.
            # F8 (review): Switch RestoreEntity (`switch.py:802-854`) is the
            # fresher fast-path (~15s attribute flush) and wins when present;
            # this KV is the durable fallback for when the switch attribute
            # is missing/unserializable. Restore ordering does NOT change at
            # runtime; the doc-vs-code mismatch was in the planning text.
            # MUST use dt_util.parse_datetime (Bug Class #13/#21) — not
            # datetime.fromisoformat which would mis-handle naive timestamps.
            # F1 (review): empty-string sentinel contract — `_save_evse_state`
            # writes "" when the window auto-expires; the `if fc_iso:`
            # truthiness guard below treats "" as falsy (no override applied).
            fc_iso = await db.restore_energy_state_with_age(
                "ev_force_charge_until", max_age_hours=STALE_MAX_AGE_HOURS,
            )
            if fc_iso:
                try:
                    parsed = dt_util.parse_datetime(fc_iso)
                    if parsed is not None:
                        # Ensure tz-aware before compare (defensive)
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=dt_util.UTC)
                        if parsed > dt_util.utcnow():
                            self._ev.set_force_charge_override(parsed)
                except (ValueError, TypeError):
                    _LOGGER.warning(
                        "Could not parse ev_force_charge_until=%r — skipping",
                        fc_iso,
                    )
            if (
                states
                or self._ev._paused_by_grid_cap
                or self._ev._paused_by_battery_drain
                or self._ev._paused_by_fill_priority
                or self._ev._paused_by_arbitrage
                or self._ev._proactive_offpeak_holds
                or self._ev._force_charge_until is not None
            ):
                _LOGGER.info(
                    "Restored EVSE state: paused=%s, excess_solar=%s, "
                    "grid_cap=%s, battery_drain=%s, fill_priority=%s, "
                    "arbitrage=%s, proactive_offpeak_holds=%s, "
                    "force_charge_until=%s",
                    list(self._ev._paused_by_us),
                    list(self._ev._excess_solar_active),
                    list(self._ev._paused_by_grid_cap),
                    list(self._ev._paused_by_battery_drain),
                    list(self._ev._paused_by_fill_priority),
                    list(self._ev._paused_by_arbitrage),
                    list(self._ev._proactive_offpeak_holds),
                    self._ev._force_charge_until.isoformat()
                    if self._ev._force_charge_until else None,
                )
        except Exception as e:
            _LOGGER.warning("Could not restore EVSE state from DB: %s", e)

    async def _save_evse_state(self) -> None:
        """Persist EVSE state to DB for restart recovery.

        v<next> WS1: extends the existing 15-min save cadence (no new timer —
        Bug Class #19/#42) with four additional KV writes:
        - `ev_force_charge_until` — canonical durable force-charge expiry
          (Switch RestoreEntity path remains as fast-path; KV wins on conflict).
          Saved as tz-aware ISO string via `dt_util.now().isoformat()` (Bug
          Class #21 — never naive).
        - `evse_fill_priority_paused` — mirrors the existing grid_cap / drain
          KV pattern.
        - `evse_arbitrage_paused` — for parity with the other guard sets
          (operator decision 4).
        - `evse_proactive_offpeak_holds` — new WS2 intent-state.
        """
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            for evse_id in self._ev._evse:
                await db.save_evse_state(
                    evse_id=evse_id,
                    paused_by_energy=evse_id in self._ev._paused_by_us,
                    excess_solar_active=evse_id in self._ev._excess_solar_active,
                )
            # Grid cap + battery drain state via key-value store
            import json as _json
            await db.save_energy_state(
                "evse_grid_cap_paused",
                _json.dumps(list(self._ev._paused_by_grid_cap)),
            )
            await db.save_energy_state(
                "evse_battery_drain_paused",
                _json.dumps(list(self._ev._paused_by_battery_drain)),
            )
            # v<next> WS1 D1.2: fill-priority pause set
            await db.save_energy_state(
                "evse_fill_priority_paused",
                _json.dumps(list(self._ev._paused_by_fill_priority)),
            )
            # v<next> WS1 D1.3b (operator decision 4): arbitrage pause set
            await db.save_energy_state(
                "evse_arbitrage_paused",
                _json.dumps(list(self._ev._paused_by_arbitrage)),
            )
            # v<next> WS1 D1.3: proactive off-peak hold intent-state
            await db.save_energy_state(
                "evse_proactive_offpeak_holds",
                _json.dumps(list(self._ev._proactive_offpeak_holds)),
            )
            # v<next> WS1 D1.1: force-charge expiry (canonical durable copy).
            # tz-aware ISO; on restore goes through dt_util.parse_datetime.
            fc_until = self._ev._force_charge_until
            if fc_until is not None:
                # Ensure tz-aware (defensive; setter only accepts UTC-aware)
                if fc_until.tzinfo is None:
                    from homeassistant.util import dt as dt_util
                    fc_until = fc_until.replace(tzinfo=dt_util.UTC)
                await db.save_energy_state(
                    "ev_force_charge_until",
                    fc_until.isoformat(),
                )
            else:
                # F1 fix-up: when the window auto-expires (energy_pool.py
                # determine_actions ~L450, _is_force_charge_active ~L583),
                # `_force_charge_until` is set back to None. Without this
                # else-branch the stale future-ISO row would linger in
                # `energy_state` and the only thing keeping it from being
                # honored on restore is the `parsed > dt_util.utcnow()`
                # future-check (fragile). Empty-string sentinel contract:
                # the restore side's `if fc_iso:` truthiness guard treats
                # "" as falsy → no override applied. Verified at
                # `_restore_evse_state` `if fc_iso:` above.
                await db.save_energy_state(
                    "ev_force_charge_until",
                    "",
                )
        except Exception as e:
            _LOGGER.warning("Could not save EVSE state to DB: %s", e)

    async def _fit_temp_regression(self) -> None:
        """Fit temperature regression from historical consumption-temperature pairs.

        Requires 30+ paired data points. Uses simple linear regression:
        consumption = base + coeff * |temp - 72|
        """
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            pairs = await db.get_energy_temp_pairs(min_days=30)
            if len(pairs) < 30:
                return

            # Simple linear regression: y = a + b*x
            # where y = consumption_kwh, x = |temp - 72|
            n = len(pairs)
            xs = [abs(t - 72.0) for _, t in pairs]
            ys = [c for c, _ in pairs]
            sum_x = sum(xs)
            sum_y = sum(ys)
            sum_xy = sum(x * y for x, y in zip(xs, ys))
            sum_x2 = sum(x * x for x in xs)

            denom = n * sum_x2 - sum_x * sum_x
            if abs(denom) < 1e-10:
                return  # Degenerate data

            coeff = (n * sum_xy - sum_x * sum_y) / denom
            base = (sum_y - coeff * sum_x) / n

            self._predictor.set_temp_regression(base, coeff)
        except Exception as e:
            _LOGGER.warning("Could not fit temperature regression: %s", e)

    # =========================================================================
    # v3.15.0: Restart resilience + Envoy offline defense
    # =========================================================================

    async def _restore_consumption_history(self) -> None:
        """Restore per-DOW consumption history from energy_daily on startup."""
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            rows = await db.get_consumption_history(days=60)
            if rows:
                self._predictor.restore_consumption_history(rows)
        except Exception as e:
            _LOGGER.warning("Could not restore consumption history: %s", e)

    async def _restore_power_profiles(self) -> None:
        """Restore room power profiles from DB on startup."""
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            rows = await db.load_power_profiles()
            if rows:
                count = self._power_profiles.restore_from_rows(rows)
                _LOGGER.info("Restored %d power profile rows from DB", count)
        except Exception as e:
            _LOGGER.warning("Could not restore power profiles: %s", e)

    async def _save_power_profiles(self) -> None:
        """Persist power profiles to DB."""
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            profiles = self._power_profiles.get_all_profiles()
            if profiles:
                await db.save_power_profiles(profiles)
        except Exception as e:
            _LOGGER.warning("Could not save power profiles: %s", e)

    async def _restore_midnight_snapshot(self) -> None:
        """Restore midnight snapshots + billing from DB on startup.

        Restores:
        - 6 lifetime sensor snapshots (if snapshot date = today)
        - Daily billing accumulators (via CostTracker.restore_daily)
        - _last_reset_date so daily reset logic works correctly
        """
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            snapshot = await db.restore_midnight_snapshot()
            if snapshot is None:
                return

            from homeassistant.util import dt as dt_util
            snapshot_date = snapshot.get("snapshot_date", "")
            today = dt_util.now().date().isoformat()

            if snapshot_date == today:
                # Restore lifetime snapshots for today's consumption tracking
                self._lifetime_consumption_snapshot = snapshot.get("lifetime_consumption")
                self._lifetime_production_snapshot = snapshot.get("lifetime_production")
                self._lifetime_net_import_snapshot = snapshot.get("lifetime_net_import")
                self._lifetime_net_export_snapshot = snapshot.get("lifetime_net_export")
                self._lifetime_battery_charged_snapshot = snapshot.get("lifetime_battery_charged")
                self._lifetime_battery_discharged_snapshot = snapshot.get("lifetime_battery_discharged")
                self._last_reset_date = today
                _LOGGER.info(
                    "Restored midnight snapshots for today (%s)", today
                )

                # Restore daily billing accumulators
                self._billing.restore_daily(snapshot)
            else:
                _LOGGER.debug(
                    "Midnight snapshot date %s != today %s, snapshots will re-seed",
                    snapshot_date, today,
                )
        except Exception as e:
            _LOGGER.warning("Could not restore midnight snapshot: %s", e)

    async def _save_midnight_snapshot(self) -> None:
        """Save snapshot of lifetime sensors + billing accumulators.

        Called at midnight (via _maybe_reset_daily), every 3rd cycle
        (via _periodic_db_writes), and at teardown.
        """
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            from homeassistant.util import dt as dt_util
            billing = self._billing.get_status()
            await db.save_midnight_snapshot({
                "snapshot_date": dt_util.now().date().isoformat(),
                "lifetime_consumption": self._lifetime_consumption_snapshot,
                "lifetime_production": self._lifetime_production_snapshot,
                "lifetime_net_import": self._lifetime_net_import_snapshot,
                "lifetime_net_export": self._lifetime_net_export_snapshot,
                "lifetime_battery_charged": self._lifetime_battery_charged_snapshot,
                "lifetime_battery_discharged": self._lifetime_battery_discharged_snapshot,
                "import_kwh_today": billing.get("import_kwh_today", 0),
                "export_kwh_today": billing.get("export_kwh_today", 0),
                "import_cost_today": billing.get("import_cost_today", 0),
                "export_credit_today": billing.get("export_credit_today", 0),
                "net_cost_today": billing.get("cost_today", 0),
            })
        except Exception as e:
            _LOGGER.warning("Could not save midnight snapshot: %s", e)

    async def _save_envoy_cache(self) -> None:
        """Cache current Envoy sensor values to DB (each decision cycle).

        Used on restart to provide last-known values when Envoy is offline.
        """
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return

        # Only cache if Envoy is currently available
        soc = self._battery.battery_soc
        if soc is None:
            return  # Envoy offline — don't overwrite good cache with None

        try:
            await db.save_envoy_cache({
                "soc": soc,
                "net_power": self._battery.net_power,
                "solar_production": self._battery.solar_production,
                "battery_power": self._battery.battery_power,
                "battery_capacity": self._predictor._get_battery_capacity_kwh(),
                "lifetime_net_import": self._get_lifetime_net_import(),
                "lifetime_net_export": self._get_lifetime_net_export(),
                "lifetime_production": self._get_lifetime_production(),
                "lifetime_consumption": self._get_lifetime_consumption(),
                "lifetime_battery_charged": self._get_lifetime_battery_charged(),
                "lifetime_battery_discharged": self._get_lifetime_battery_discharged(),
            })
        except Exception as e:
            _LOGGER.warning("Could not save envoy cache: %s", e)

    async def _restore_envoy_cache(self) -> None:
        """Restore last-known Envoy values from DB on startup.

        Used to populate battery_full_time hold cache and provide fallback
        values when Envoy is slow to come online after HA restart.
        Skips if cache is older than 4 hours (stale after extended downtime).
        """
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            cache = await db.restore_envoy_cache()
            if cache is None:
                return

            # Staleness check: skip if cache is older than 4 hours
            from homeassistant.util import dt as dt_util
            updated_at = cache.get("updated_at")
            if updated_at:
                try:
                    cache_time = dt_util.parse_datetime(updated_at)
                    if cache_time is not None:
                        age_hours = (dt_util.utcnow() - cache_time).total_seconds() / 3600
                        if age_hours > 4:
                            _LOGGER.info(
                                "Envoy cache is %.1f hours old, skipping restore",
                                age_hours,
                            )
                            return
                except (ValueError, TypeError):
                    pass

            # Restore battery_full_time hold cache from cached SOC
            cached_soc = cache.get("soc")
            if cached_soc is not None and cached_soc >= 99:
                self._last_battery_full_time = "already_full"

            _LOGGER.info(
                "Restored envoy cache: SOC=%.0f%%, net_power=%.1f kW",
                cached_soc or 0, cache.get("net_power") or 0,
            )
        except Exception as e:
            _LOGGER.warning("Could not restore envoy cache: %s", e)

    async def _restore_load_shedding_level(self) -> None:
        """Restore load shedding active level from DB on startup.

        Sets a grace period to prevent immediate de-escalation before
        sustained readings buffer refills.
        """
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            level_str = await db.restore_energy_state("load_shedding_level")
            if level_str is not None:
                self._load_shedding_active_level = int(level_str)
                if self._load_shedding_active_level > 0:
                    # Grace period: suppress de-escalation for a few cycles
                    # so the sustained readings buffer can refill
                    self._load_shedding_grace_cycles = 3
                    _LOGGER.info(
                        "Restored load shedding level: %d (grace period: %d cycles)",
                        self._load_shedding_active_level,
                        self._load_shedding_grace_cycles,
                    )
        except (ValueError, TypeError):
            pass
        except Exception as e:
            _LOGGER.warning("Could not restore load shedding level: %s", e)

    async def _save_load_shedding_level(self) -> None:
        """Persist load shedding level to DB."""
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            await db.save_energy_state(
                "load_shedding_level", str(self._load_shedding_active_level)
            )
        except Exception as e:
            _LOGGER.warning("Could not save load shedding level: %s", e)

    def _get_lifetime_consumption(self) -> float | None:
        """Read Envoy lifetime energy consumption (MWh, monotonically increasing)."""
        return self._get_state_float(self._entity_lifetime_consumption)

    def _get_lifetime_production(self) -> float | None:
        """Read Envoy lifetime energy production (MWh, monotonically increasing)."""
        return self._get_state_float(self._entity_lifetime_production)

    def _get_lifetime_net_import(self) -> float | None:
        """Read Envoy lifetime net energy consumption/import (MWh, monotonically increasing)."""
        return self._get_state_float(self._entity_lifetime_net_import)

    def _get_lifetime_net_export(self) -> float | None:
        """Read Envoy lifetime net energy production/export (MWh, monotonically increasing)."""
        return self._get_state_float(self._entity_lifetime_net_export)

    def _get_lifetime_battery_discharged(self) -> float | None:
        """Read Envoy lifetime battery energy discharged (MWh, monotonically increasing)."""
        return self._get_state_float(self._entity_lifetime_battery_discharged)

    def _get_lifetime_battery_charged(self) -> float | None:
        """Read Envoy lifetime battery energy charged (MWh, monotonically increasing)."""
        return self._get_state_float(self._entity_lifetime_battery_charged)

    def _maybe_reset_daily(self) -> None:
        """Reset daily counters and feed accuracy tracking if date changed.

        v3.14.0: Derives true daily consumption from 5 independent lifetime sensors:
        actual = grid_import + (solar_produced - solar_exported) + (battery_discharged - battery_charged)
        The (solar_produced - solar_exported) term includes solar that charged the battery,
        so we must subtract battery_charged to avoid double-counting.
        With net-consumption CT, lifetime_energy_consumption = net grid import only,
        NOT total home consumption. The derived formula is accurate regardless of CT mode.
        Must run BEFORE billing.accumulate() to capture yesterday's totals.
        """
        from homeassistant.util import dt as dt_util
        today = dt_util.now().date().isoformat()

        # Read all 6 lifetime values for snapshot tracking
        current_lifetime = self._get_lifetime_consumption()
        current_production = self._get_lifetime_production()
        current_net_import = self._get_lifetime_net_import()
        current_net_export = self._get_lifetime_net_export()
        current_battery_charged = self._get_lifetime_battery_charged()
        current_battery_discharged = self._get_lifetime_battery_discharged()

        if today != self._last_reset_date:
            # Capture yesterday's billing totals BEFORE they're reset
            yesterday_totals = self._billing.get_yesterday_totals()

            # Calculate yesterday's actual consumption from lifetime deltas
            actual_kwh = None
            solar_produced_kwh = None

            # v3.14.0: Primary path — derive from 5 independent lifetime sensors
            if (
                self._lifetime_production_snapshot is not None
                and self._lifetime_net_import_snapshot is not None
                and self._lifetime_net_export_snapshot is not None
                and self._lifetime_battery_charged_snapshot is not None
                and self._lifetime_battery_discharged_snapshot is not None
                and current_production is not None
                and current_net_import is not None
                and current_net_export is not None
                and current_battery_charged is not None
                and current_battery_discharged is not None
                and self._last_reset_date
            ):
                # Lifetime values are in MWh — convert deltas to kWh
                grid_import_kwh = (current_net_import - self._lifetime_net_import_snapshot) * 1000.0
                solar_produced_kwh = (current_production - self._lifetime_production_snapshot) * 1000.0
                solar_exported_kwh = (current_net_export - self._lifetime_net_export_snapshot) * 1000.0
                battery_charged_kwh = (current_battery_charged - self._lifetime_battery_charged_snapshot) * 1000.0
                battery_discharged_kwh = (current_battery_discharged - self._lifetime_battery_discharged_snapshot) * 1000.0

                # Guard: negative delta means Envoy reboot mid-day — skip derived path
                if (
                    grid_import_kwh < 0 or solar_produced_kwh < 0
                    or solar_exported_kwh < 0 or battery_charged_kwh < 0
                    or battery_discharged_kwh < 0
                ):
                    _LOGGER.warning(
                        "Negative lifetime delta detected (possible Envoy reboot), "
                        "skipping derived consumption"
                    )
                    actual_kwh = None
                    solar_produced_kwh = None
                else:
                    # solar_self_consumed includes solar→battery, so subtract battery_charged
                    # to avoid double-counting: consumption = grid + solar_self - battery_charged + battery_discharged
                    solar_self_consumed = solar_produced_kwh - solar_exported_kwh
                    net_battery_kwh = battery_discharged_kwh - battery_charged_kwh
                    actual_kwh = grid_import_kwh + solar_self_consumed + net_battery_kwh
                    _LOGGER.info(
                        "Derived consumption: grid=%.1f + solar_self=%.1f + net_battery=%.1f = %.1f kWh",
                        grid_import_kwh, solar_self_consumed, net_battery_kwh, actual_kwh,
                    )
            # Fallback: legacy delta (net grid import only, known inaccurate with net-consumption CT)
            elif (
                self._lifetime_consumption_snapshot is not None
                and current_lifetime is not None
                and self._last_reset_date
            ):
                delta_mwh = current_lifetime - self._lifetime_consumption_snapshot
                actual_kwh = delta_mwh * 1000.0
                _LOGGER.warning(
                    "Using legacy consumption delta (net import only) = %.1f kWh — "
                    "derived sensors not yet available",
                    actual_kwh,
                )

            # Guard: reject negative or zero actual consumption (e.g., partial Envoy reboot)
            if actual_kwh is not None and actual_kwh <= 0:
                _LOGGER.warning(
                    "Computed consumption %.1f kWh is non-positive, discarding", actual_kwh
                )
                actual_kwh = None
                solar_produced_kwh = None

            accuracy_result = None
            predicted_consumption = None

            if actual_kwh is not None:
                self._predictor.record_actual_consumption(actual_kwh)

                # Evaluate yesterday's forecast accuracy
                forecast = self._predictor._get_current_prediction()
                predicted_consumption = forecast.get("predicted_consumption_kwh")
                accuracy_result = self._accuracy.evaluate_accuracy(
                    predicted_consumption, actual_kwh, self._last_reset_date
                )
                if accuracy_result:
                    _LOGGER.info(
                        "Forecast accuracy: predicted=%.1f actual=%.1f error=%.1f kWh (%.1f%%)",
                        predicted_consumption or 0,
                        actual_kwh,
                        accuracy_result["error_kwh"],
                        accuracy_result["pct_error"],
                    )

                # Feed Bayesian adjustment back to predictor
                self._predictor._adjustment_factor = self._accuracy.get_adjustment_factor()

                # v3.13.3: Feed solar forecast error baseline
                if accuracy_result:
                    self._solar_forecast_error_baseline.update(
                        abs(accuracy_result["pct_error"])
                    )

            # v3.13.3: Feed daily import cost baseline
            if yesterday_totals:
                import_cost = yesterday_totals.get("import_cost", 0)
                if import_cost > 0:
                    self._daily_import_cost_baseline.update(import_cost)

            # Save daily snapshot to DB (async fire-and-forget)
            if yesterday_totals:
                error_pct = accuracy_result["pct_error"] if accuracy_result else None
                adj_factor = self._accuracy.get_adjustment_factor() if accuracy_result else None
                avg_temp = self._predictor._prediction_temperature
                self.hass.async_create_task(
                    self._save_daily_snapshot(
                        yesterday_totals,
                        actual_kwh,
                        solar_production_kwh=solar_produced_kwh,
                        predicted_consumption_kwh=predicted_consumption,
                        prediction_error_pct=error_pct,
                        adjustment_factor=adj_factor,
                        avg_temperature=avg_temp,
                    )
                )

            # v3.11.0: Daily DB cleanup
            self.hass.async_create_task(self._daily_db_cleanup())

            # Reset ALL 6 snapshots for new day
            self._lifetime_consumption_snapshot = current_lifetime
            self._lifetime_production_snapshot = current_production
            self._lifetime_net_import_snapshot = current_net_import
            self._lifetime_net_export_snapshot = current_net_export
            self._lifetime_battery_charged_snapshot = current_battery_charged
            self._lifetime_battery_discharged_snapshot = current_battery_discharged
            self._tou_transition_count = 0
            self._last_reset_date = today

            # v3.15.0: Persist new day's midnight snapshot immediately
            self.hass.async_create_task(self._save_midnight_snapshot())
        else:
            # Seed each snapshot independently as entities become available
            if self._lifetime_consumption_snapshot is None and current_lifetime is not None:
                self._lifetime_consumption_snapshot = current_lifetime
            if self._lifetime_production_snapshot is None and current_production is not None:
                self._lifetime_production_snapshot = current_production
            if self._lifetime_net_import_snapshot is None and current_net_import is not None:
                self._lifetime_net_import_snapshot = current_net_import
            if self._lifetime_net_export_snapshot is None and current_net_export is not None:
                self._lifetime_net_export_snapshot = current_net_export
            if self._lifetime_battery_charged_snapshot is None and current_battery_charged is not None:
                self._lifetime_battery_charged_snapshot = current_battery_charged
            if self._lifetime_battery_discharged_snapshot is None and current_battery_discharged is not None:
                self._lifetime_battery_discharged_snapshot = current_battery_discharged

    async def _save_daily_snapshot(
        self,
        totals: dict,
        consumption_kwh: float | None,
        solar_production_kwh: float | None = None,
        predicted_consumption_kwh: float | None = None,
        prediction_error_pct: float | None = None,
        adjustment_factor: float | None = None,
        avg_temperature: float | None = None,
    ) -> None:
        """Save yesterday's billing totals to energy_daily table."""
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            await db.log_energy_daily(
                date_str=totals["date"],
                import_kwh=totals["import_kwh"],
                export_kwh=totals["export_kwh"],
                import_cost=totals["import_cost"],
                export_credit=totals["export_credit"],
                net_cost=totals["net_cost"],
                consumption_kwh=consumption_kwh,
                solar_production_kwh=solar_production_kwh,
                predicted_consumption_kwh=predicted_consumption_kwh,
                avg_temperature=avg_temperature,
                prediction_error_pct=prediction_error_pct,
                adjustment_factor=adjustment_factor,
            )
            _LOGGER.info(
                "Saved daily energy snapshot for %s: import=%.1f export=%.1f cost=$%.2f",
                totals["date"], totals["import_kwh"], totals["export_kwh"],
                totals["net_cost"],
            )
        except Exception as e:
            _LOGGER.error("Failed to save daily energy snapshot: %s", e)

    def _track_envoy_availability(self, decision: dict[str, Any]) -> None:
        """Track Envoy availability and alert on extended outages."""
        from homeassistant.util import dt as dt_util

        envoy_ok = decision.get("envoy_available", True)
        if envoy_ok:
            if self._envoy_unavailable_count > 0:
                _LOGGER.info(
                    "Envoy reconnected after %d unavailable cycles",
                    self._envoy_unavailable_count,
                )
            self._envoy_unavailable_count = 0
            self._envoy_last_available = dt_util.now().isoformat()
            # D7: clear degraded flag on recovery.
            self._envoy_degraded = False
            self._envoy_degraded_since = None
        else:
            self._envoy_unavailable_count += 1
            # D7: mark degraded; stamp `_since` on first unavailable cycle.
            if not self._envoy_degraded:
                self._envoy_degraded = True
                self._envoy_degraded_since = dt_util.now().isoformat()
            # Alert via NM after 3 consecutive misses (~15 minutes)
            if self._envoy_unavailable_count == 3:
                self.hass.async_create_task(
                    self._send_nm_alert(
                        title="Envoy Offline",
                        message=(
                            f"Envoy has been unavailable for "
                            f"{self._envoy_unavailable_count * self._decision_interval} minutes. "
                            f"Battery strategy is holding — no commands being issued."
                        ),
                        severity="high",
                        hazard_type="envoy_offline",
                        location="main_panel",
                    )
                )

    def _crosscheck_consumption(self) -> None:
        """Cross-check our lifetime consumption delta against Envoy's energy_consumption_today.

        Runs once per hour. Both sides measure net grid import (with net-consumption CT),
        so divergence indicates Envoy reboot or stale snapshot rather than CT mode issues.
        The actual consumption calculation uses the derived formula in _maybe_reset_daily().
        """
        from homeassistant.util import dt as dt_util
        now = dt_util.now()

        # Only check once per hour to avoid log noise
        if now.hour == self._last_crosscheck_hour:
            return

        # Need both data sources
        current_lifetime = self._get_lifetime_consumption()
        if current_lifetime is None or self._lifetime_consumption_snapshot is None:
            return

        # v4.3.1: None-safe — _entity_consumption_today is None when EC was
        # instantiated without an envoy entity (validation gate would normally
        # block this; defensive guard).
        if self._entity_consumption_today is None:
            return
        envoy_today_state = self.hass.states.get(self._entity_consumption_today)
        if envoy_today_state is None or envoy_today_state.state in ("unknown", "unavailable"):
            return

        try:
            envoy_today_kwh = float(envoy_today_state.state)
        except (ValueError, TypeError):
            return

        # Our delta (MWh → kWh)
        our_delta_kwh = (current_lifetime - self._lifetime_consumption_snapshot) * 1000.0

        self._last_crosscheck_hour = now.hour

        # Skip early morning when both values are near zero
        if envoy_today_kwh < 1.0 and our_delta_kwh < 1.0:
            return

        # Check divergence
        reference = max(envoy_today_kwh, our_delta_kwh, 0.1)
        divergence_pct = abs(envoy_today_kwh - our_delta_kwh) / reference * 100

        if divergence_pct > 15:
            _LOGGER.warning(
                "Consumption cross-check divergence: Envoy today=%.2f kWh, "
                "our lifetime delta=%.2f kWh (%.1f%% off). "
                "Possible Envoy reboot or stale snapshot.",
                envoy_today_kwh,
                our_delta_kwh,
                divergence_pct,
            )
            # v4.3.0 D6: surface the anomaly to EnvoyStatusSensor so it can
            # flip from "online" to "stale" even when state objects are fresh.
            self._envoy_data_anomaly_at = dt_util.now().isoformat()
            # v4.6.1 canary: also persist to unified anomaly_log via AnomalyEvent.
            # Parallel write — existing in-memory flag and sensor derivation unchanged.
            self.hass.async_create_task(
                self._store_crosscheck_anomaly_event(
                    envoy_today_kwh=envoy_today_kwh,
                    our_delta_kwh=our_delta_kwh,
                    divergence_pct=divergence_pct,
                )
            )
        elif divergence_pct < 5 and self._envoy_data_anomaly_at is not None:
            # v4.3.0 Review M15 fix: clear anomaly on recovery so the sensor
            # reflects current reality, not a stale 1-hour stale window.
            _LOGGER.info(
                "Consumption cross-check recovered (divergence %.1f%% < 5%%); "
                "clearing envoy data anomaly flag.",
                divergence_pct,
            )
            self._envoy_data_anomaly_at = None

            # If Envoy's daily value is significantly higher, our snapshot may
            # be stale (Envoy rebooted and lifetime reset). Re-seed all snapshots.
            if envoy_today_kwh > our_delta_kwh * 2 and our_delta_kwh < 5:
                _LOGGER.warning(
                    "Re-seeding all lifetime snapshots — likely Envoy reboot detected"
                )
                self._lifetime_consumption_snapshot = current_lifetime
                # v3.14.0: Also re-seed derived formula snapshots
                cp = self._get_lifetime_production()
                if cp is not None:
                    self._lifetime_production_snapshot = cp
                cni = self._get_lifetime_net_import()
                if cni is not None:
                    self._lifetime_net_import_snapshot = cni
                cne = self._get_lifetime_net_export()
                if cne is not None:
                    self._lifetime_net_export_snapshot = cne
                cbc = self._get_lifetime_battery_charged()
                if cbc is not None:
                    self._lifetime_battery_charged_snapshot = cbc
                cbd = self._get_lifetime_battery_discharged()
                if cbd is not None:
                    self._lifetime_battery_discharged_snapshot = cbd

    async def _store_crosscheck_anomaly_event(
        self,
        envoy_today_kwh: float,
        our_delta_kwh: float,
        divergence_pct: float,
    ) -> None:
        """Persist energy cross-check divergence as a unified AnomalyEvent.

        v4.6.1 canary migration: parallel write alongside the existing
        in-memory _envoy_data_anomaly_at flag. The sensor's stale-derivation
        logic is unaffected — this only adds DB persistence.
        """
        from .anomaly_event import AnomalyEvent, AnomalySeverity, AnomalyType
        from homeassistant.util import dt as _dt_util

        db = self.hass.data.get(_DOMAIN, {}).get("database")
        if db is None:
            return

        event = AnomalyEvent(
            coordinator="energy",
            type="energy.crosscheck_divergence",
            severity=AnomalySeverity.WARNING,
            anomaly_type=AnomalyType.POINT_IN_TIME,
            detected_at=_dt_util.utcnow().isoformat(),
            payload={
                "envoy_today_kwh": envoy_today_kwh,
                "our_delta_kwh": our_delta_kwh,
                "divergence_pct": round(divergence_pct, 2),
            },
            entity_id=self._entity_consumption_today,
        )
        await db.save_anomaly_event(event)

    # =========================================================================
    # v3.11.0 D1/D2: Energy History + External Conditions Logging
    # =========================================================================

    async def _log_energy_history_snapshot(self, decision: dict[str, Any]) -> None:
        """Log energy history snapshot to DB (every ~15 min).

        Values are instantaneous power in kW (converted from Envoy watts).
        DB columns are labeled "energy flows" historically but store point-in-time
        power readings at 15-min intervals.

        v3.13.1: Now populates all 19 columns including house_avg_temp,
        house_avg_humidity, deltas, rooms_occupied, outside_humidity, tou_period.
        """
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            # v4.5.0 unit-consistency sweep: use the _w properties which
            # normalize Envoy kW/W firmware variants. Pre-v4.5.0 this site
            # divided the raw entity value by 1000, which silently broke if
            # the user's Envoy reported in kW (same bug class as v4.3.4
            # battery_power_w fix).
            solar_prod_w = self._battery.solar_production_w
            net_power_w = self._battery.net_power_w
            solar_prod_kw = solar_prod_w / 1000.0 if solar_prod_w is not None else None
            grid_import_kw = max(net_power_w or 0, 0) / 1000.0
            solar_export_kw = abs(min(net_power_w or 0, 0)) / 1000.0

            outside_temp = None
            outside_humidity = None
            # v4.7.x Cycle A: route through WeatherProviderManager (A4 migration)
            _active_weather_eid = self._get_active_weather_entity()
            weather_state = self.hass.states.get(_active_weather_eid) if _active_weather_eid else None
            if weather_state and weather_state.attributes:
                outside_temp = weather_state.attributes.get("temperature")
                outside_humidity = weather_state.attributes.get("humidity")

            # v4.5.0 unit-consistency: use total_consumption_w which
            # normalizes kW/W firmware variants. The historical
            # `total_consumption_kw` property is mis-named (returns raw
            # entity value, not always kW) — kept for back-compat callers.
            consumption_w = self.total_consumption_w
            consumption_kw = consumption_w / 1000.0 if consumption_w is not None else None

            # v3.13.1: Indoor averages from room coordinators
            house_avg_temp, house_avg_humidity = self._get_house_avg_climate()

            # v3.13.1: Compute deltas
            temp_delta = None
            if house_avg_temp is not None and outside_temp is not None:
                temp_delta = house_avg_temp - outside_temp
            humidity_delta = None
            if house_avg_humidity is not None and outside_humidity is not None:
                humidity_delta = house_avg_humidity - outside_humidity

            # v3.13.1: Occupied room count from presence coordinator
            rooms_occupied = self._get_occupied_room_count()

            # v3.13.1: TOU period
            tou_period = None
            try:
                tou_period = self._tou.get_current_period()
            except Exception:
                pass

            # v4.2.17: Read Emporia mains import power for grid_import_2
            grid_import_2_kw = None
            if self._grid_import_entity:
                gi_state = self.hass.states.get(self._grid_import_entity)
                if gi_state and gi_state.state not in ("unknown", "unavailable"):
                    try:
                        gi_val = float(gi_state.state)
                        uom = gi_state.attributes.get("unit_of_measurement", "W")
                        if uom == "kW":
                            grid_import_2_kw = max(gi_val, 0)
                        else:
                            # Assume watts
                            grid_import_2_kw = max(gi_val, 0) / 1000.0
                    except (ValueError, TypeError):
                        pass

            await db.log_energy_history({
                "solar_production": solar_prod_kw,
                "solar_export": solar_export_kw,
                "grid_import": grid_import_kw,
                "grid_import_2": grid_import_2_kw,
                "battery_level": self._battery.battery_soc,
                "whole_house_energy": consumption_kw,
                "rooms_energy_total": self._get_rooms_energy_total(),
                "outside_temp": outside_temp,
                "outside_humidity": outside_humidity,
                "house_avg_temp": house_avg_temp,
                "house_avg_humidity": house_avg_humidity,
                "temp_delta_outside": temp_delta,
                "humidity_delta_outside": humidity_delta,
                "rooms_occupied": rooms_occupied,
                "tou_period": tou_period,
            })
        except Exception as e:
            _LOGGER.warning("Failed to log energy history: %s", e)

    async def _log_external_conditions_snapshot(self) -> None:
        """Log external conditions snapshot to DB (every ~15 min).

        v3.13.1: occupied_room_count and occupied_zone_count now read from
        presence coordinator instead of being hardcoded to 0.
        """
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            # v4.7.x Cycle A: route through WeatherProviderManager (A4 migration)
            _active_weather_eid = self._get_active_weather_entity()
            weather_state = self.hass.states.get(_active_weather_eid) if _active_weather_eid else None
            outside_temp = None
            outside_humidity = None
            weather_condition = None
            if weather_state:
                weather_condition = weather_state.state
                if weather_state.attributes:
                    outside_temp = weather_state.attributes.get("temperature")
                    outside_humidity = weather_state.attributes.get("humidity")

            # v4.5.0 unit-consistency: normalize via solar_production_w which
            # checks the entity's unit_of_measurement (kW vs W).
            solar_prod_w = self._battery.solar_production_w
            solar_prod_kw = solar_prod_w / 1000.0 if solar_prod_w is not None else None

            # v3.13.1: Read real occupancy counts from presence coordinator
            occupied_rooms, occupied_zones = self._get_occupancy_counts()

            await db.log_external_conditions({
                "outside_temp": outside_temp,
                "outside_humidity": outside_humidity,
                "weather_condition": weather_condition,
                "solar_production": solar_prod_kw,
                "forecast_high": self._cached_forecast_high,
                "forecast_low": self._cached_forecast_low,
                "occupied_room_count": occupied_rooms,
                "occupied_zone_count": occupied_zones,
            })
        except Exception as e:
            _LOGGER.warning("Failed to log external conditions: %s", e)

    async def _daily_db_cleanup(self) -> None:
        """Run daily DB cleanup for energy_history and external_conditions."""
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            await db.cleanup_energy_history(retention_days=180)
            await db.cleanup_external_conditions(retention_days=90)
        except Exception as e:
            _LOGGER.warning("Failed to run daily DB cleanup: %s", e)

    # =========================================================================
    # v4.3.0 D4: Arbitrage cycle accounting
    # =========================================================================

    # Round-trip efficiency assumption for Enphase IQ batteries.
    # Used to discount nominal savings since not all kWh imported at off-peak
    # is recoverable at peak (charge/discharge losses).
    _ARBITRAGE_RTE: float = 0.90

    def _get_battery_capacity_kwh(self) -> float:
        """Best-effort battery capacity in kWh.

        Reads the auto-derived Envoy battery_capacity entity (Wh) when
        available; remembers the last good value so an Envoy blip during
        arbitrage doesn't silently flip to the 40 kWh fallback mid-cycle.
        Logs a WARNING on first fallback so the user sees it.

        v4.3.1: battery_capacity entity has no production default — `eid` may
        be None when not configured (e.g., installs without battery). Treat
        same as unavailable: use cached value, then static fallback.
        """
        from .energy_forecast import BATTERY_TOTAL_CAPACITY_KWH_FALLBACK
        eid = self._battery._get_entity("battery_capacity")
        if eid is not None:
            state = self.hass.states.get(eid)
            if state is not None and state.state not in ("unknown", "unavailable"):
                try:
                    raw = float(state.state)
                    # Unit-consistency: Enphase Encharge reports capacity in
                    # Wh, but check uom rather than hardcoding the divisor so
                    # a kWh-reporting firmware/integration doesn't collapse
                    # capacity to ~0.04 kWh and silently flip to the static
                    # fallback (mirrors the _read_power_w kW/W guard).
                    uom = state.attributes.get("unit_of_measurement", "")
                    if uom in ("kWh", "kwh"):
                        cap = raw
                    else:
                        cap = raw / 1000.0  # Wh → kWh
                    self._cached_battery_capacity_kwh = cap
                    return cap
                except (ValueError, TypeError):
                    pass
        # Last-known-good wins over the static fallback
        cached = getattr(self, "_cached_battery_capacity_kwh", None)
        if cached is not None:
            return cached
        if not getattr(self, "_capacity_fallback_logged", False):
            _LOGGER.warning(
                "Battery capacity entity %s; using static fallback %.1f kWh "
                "for arbitrage savings math. ROI sensors will be approximate "
                "until Envoy reports capacity again.",
                eid or "(not configured)",
                BATTERY_TOTAL_CAPACITY_KWH_FALLBACK,
            )
            self._capacity_fallback_logged = True
        return BATTERY_TOTAL_CAPACITY_KWH_FALLBACK

    def _get_displaced_rate(self, season: str) -> float:
        """Return the import rate this arbitrage cycle is displacing.

        Summer: peak rate (4-hour window 16:00–20:00).
        Shoulder/winter: mid_peak rate (no peak period exists).

        M7 / C2-MED-2: reads from the LIVE TOU engine (same source as the
        D1b rate-spread gate + buy-side `get_effective_import_rate`), so a
        custom `tou_rates.json` is respected end-to-end. Falls back to the
        static `PEC_TOU_RATES` const only if the live engine cannot
        resolve the schedule (conservative — keeps the prior shape).
        """
        rates = None
        if self._tou is not None:
            try:
                rates = self._tou._rates
            except Exception:  # noqa: BLE001
                rates = None
        if rates is None:
            from .energy_const import PEC_TOU_RATES
            rates = PEC_TOU_RATES
        season_data = rates.get(season, {}).get("periods", {})
        if season == "summer" and "peak" in season_data:
            return float(season_data["peak"]["import_rate"])
        if "mid_peak" in season_data:
            return float(season_data["mid_peak"]["import_rate"])
        # Defensive fallback — should never hit
        return self._tou.get_current_rate()

    async def _account_arbitrage_cycle(
        self, decision: dict[str, Any], period: str, season: str,
    ) -> None:
        """Persist a row in arbitrage_cycles when CHARGE was active and SOC rose.

        Idempotent: only writes when there's a positive SOC delta vs. the
        previous tick. Resets state when CHARGE phase ends.

        v4.5.0 D1: gate on `arbitrage_phase == "charge"` rather than the
        broader `arbitrage_active` (which is also True during HOLD). HOLD's
        SOC rise comes from solar overcharging, not grid charge — counting
        it as arbitrage-displaced kWh would inflate savings. The savings
        formula assumes off-peak grid kWh × (displaced − off-peak rate).
        """
        # Cycle EC/HC reboot pickup: ATTAIN is also a grid-charging phase
        # (peak-buffer catch-up). Bug Class #22 — count SOC delta during
        # ATTAIN toward arbitrage savings; the kWh delivered by grid during
        # off-peak displaces high-rate import the same way arbitrage CHARGE
        # does. Skipping ATTAIN here would silently under-report savings.
        from .energy_battery import ARBITRAGE_PHASE_ATTAIN, ARBITRAGE_PHASE_CHARGE
        if decision.get("arbitrage_phase") not in (
            ARBITRAGE_PHASE_CHARGE, ARBITRAGE_PHASE_ATTAIN,
        ):
            self._arbitrage_prev_soc = None
            return

        soc_now = decision.get("soc")
        if soc_now is None:
            return  # envoy blip — wait for next tick
        soc_now = float(soc_now)

        if self._arbitrage_prev_soc is None:
            # First tick of this arbitrage segment — capture baseline only
            self._arbitrage_prev_soc = soc_now
            _LOGGER.info(
                "Arbitrage cycle start: SOC=%.1f%%, peak_buffer_target=%d%%, season=%s",
                soc_now, self._battery._peak_buffer_target, season,
            )
            return

        delta_soc = soc_now - self._arbitrage_prev_soc
        if delta_soc <= 0:
            # No charge this cycle (e.g., Enphase still ramping). Don't log a row.
            self._arbitrage_prev_soc = soc_now
            return

        # Fix-up pass (A-MED-1): during ATTAIN, exclude SOC-rise ticks where
        # the battery's grid-charge component is <= solar surplus — those
        # ticks are solar-driven, not arbitrage-displaced. Simplest defensible
        # method: skip the savings row when battery_power_w shows the battery
        # charging at or below current solar production (i.e. all charge
        # power could have come from solar). Documented in review ledger.
        if decision.get("arbitrage_phase") == ARBITRAGE_PHASE_ATTAIN:
            battery_w = self._battery.battery_power_w
            solar_w = self._battery.solar_production_w
            if (
                battery_w is not None
                and solar_w is not None
                and battery_w > 0  # actually charging
                and battery_w <= solar_w  # could be entirely solar
            ):
                # Solar-driven rise during ATTAIN — don't book as arbitrage.
                self._arbitrage_prev_soc = soc_now
                return

        capacity_kwh = self._get_battery_capacity_kwh()
        kwh_charged = (delta_soc / 100.0) * capacity_kwh
        off_peak_rate = self._tou.get_effective_import_rate()
        displaced_rate = self._get_displaced_rate(season)
        savings = kwh_charged * (displaced_rate - off_peak_rate) * self._ARBITRAGE_RTE

        # v4.3.0 Review C1 fix: ADVANCE the baseline BEFORE the DB write so a
        # transient DB failure (lock contention, write timeout) doesn't cause
        # the next tick to double-count kWh against a stale prev_soc.
        # Snapshot the prior value for the log and the DB row.
        prev_soc_for_log = self._arbitrage_prev_soc
        self._arbitrage_prev_soc = soc_now

        if savings < 0:
            # Defensive — displaced should be > off-peak; if not, don't log
            # (would corrupt counterfactual math). Baseline already advanced.
            return

        # v4.5.20: bare `DOMAIN` was undefined — module-level import is
        # aliased as `_DOMAIN` (line 30, for lambda closures). Use the
        # alias here. This bug had been silently swallowed at debug level
        # in the outer _async_decision_cycle since the arbitrage feature
        # shipped — every cycle threw NameError, arbitrage savings rows
        # never landed in DB. Caught by v4.5.20 swallow escalation on
        # the FIRST cycle after deploy. Two affected sites (here + line 1694).
        database = self.hass.data.get(_DOMAIN, {}).get("database")
        if database is not None:
            from homeassistant.util import dt as dt_util
            await database.save_arbitrage_cycle(
                timestamp=dt_util.utcnow().isoformat(),
                soc_before=prev_soc_for_log,
                soc_after=soc_now,
                kwh_charged=kwh_charged,
                off_peak_rate=off_peak_rate,
                displaced_rate=displaced_rate,
                round_trip_efficiency=self._ARBITRAGE_RTE,
                savings=savings,
                season=season,
            )

        _LOGGER.info(
            "Arbitrage cycle: SOC %.1f→%.1f (Δ%.1f), %.3f kWh charged, "
            "off-peak $%.4f → displaced $%.4f, RTE %.2f, savings $%.4f",
            prev_soc_for_log, soc_now, delta_soc, kwh_charged,
            off_peak_rate, displaced_rate, self._ARBITRAGE_RTE, savings,
        )

    async def _refresh_arbitrage_status_cache(self) -> None:
        """Refresh DB-derived savings rollups for synchronous sensor reads.

        Runs once per decision tick (5 min). Five queries — small + indexed
        on timestamp; cost is dominated by the connection open.

        v4.3.0 Review L24: the cache is **sticky on failure** by design. The
        success-path assignment to ``self._arbitrage_status_cache`` only runs
        after all 5 queries return; on any exception we log DEBUG and bail
        out, leaving the prior (slightly-stale) cache in place. This is
        preferred over clearing on failure (which would cause sensor flicker
        every transient DB-lock event). No retry loop is added because
        per-query timeout is already 5s and a fast retry rarely succeeds; an
        extra round-trip would risk blowing the decision-tick budget.

        v4.3.0 Review M12: log refresh latency at DEBUG so future reviews can
        see if it grows beyond the decision-tick budget.
        """
        # v4.5.20: use module-level _DOMAIN alias (line 30) instead of
        # bare `DOMAIN` which was undefined. See _account_arbitrage_cycle
        # for the full bug story.
        database = self.hass.data.get(_DOMAIN, {}).get("database")
        if database is None:
            return
        import time
        _t_start = time.monotonic()
        try:
            from homeassistant.util import dt as dt_util
            now = dt_util.now()
            # "Today" = since local midnight, expressed as UTC ISO for the
            # timestamp comparison in the DB (we store UTC).
            today_local_midnight = now.replace(
                hour=0, minute=0, second=0, microsecond=0,
            )
            today_utc_iso = dt_util.as_utc(today_local_midnight).isoformat()

            # "This cycle" = since bill cycle start day, local midnight.
            # v4.3.0 Review H4/H5 fix: use dt_util.parse_datetime which handles
            # tz-aware ISO strings; fall back to fromisoformat only for naive
            # date strings (YYYY-MM-DD), and explicitly localize via dt_util
            # rather than `replace(tzinfo=now.tzinfo)` which is fragile across
            # DST and historical-tz boundaries.
            cycle_start_iso = today_utc_iso
            try:
                billing = self.billing_status or {}
                cycle_start_str = billing.get("cycle_start_date")
                if cycle_start_str:
                    parsed = dt_util.parse_datetime(cycle_start_str)
                    if parsed is None:
                        # Naive YYYY-MM-DD — interpret as local-midnight via dt_util
                        from datetime import datetime as _dt
                        parsed_naive = _dt.fromisoformat(cycle_start_str)
                        if parsed_naive.tzinfo is None:
                            parsed_naive = parsed_naive.replace(
                                hour=0, minute=0, second=0, microsecond=0,
                            )
                            parsed = dt_util.as_local(
                                parsed_naive.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
                            )
                    if parsed is not None:
                        cycle_start_local = dt_util.as_local(parsed).replace(
                            hour=0, minute=0, second=0, microsecond=0,
                        )
                        cycle_start_iso = dt_util.as_utc(cycle_start_local).isoformat()
            except Exception:
                # v4.5.20: was debug. Inner step inside _refresh_arbitrage_status_cache.
                # Falling through to today_utc_iso is the recoverable default,
                # so this stays at WARNING (caller can still compute cycle stats
                # with the fallback timestamp).
                _LOGGER.warning(
                    "Arbitrage: cycle_start parse fell through",
                    exc_info=True,
                )

            today = await database.query_arbitrage_savings_since(today_utc_iso)
            cycle = await database.query_arbitrage_savings_since(cycle_start_iso)
            total = await database.query_arbitrage_savings_total()
            last_cycle = await database.query_arbitrage_last_cycle()
            pace = await database.query_arbitrage_pace_recent(days=7)

            self._arbitrage_status_cache = {
                "today": today,
                "cycle": cycle,
                "total": total,
                "last_cycle": last_cycle,
                "pace": pace,
            }
            _LOGGER.debug(
                "Arbitrage cache refresh: %.3fs (5 queries)",
                time.monotonic() - _t_start,
            )
        except Exception:
            # v4.5.20: was debug — HIGH-severity periodic-closure shape per
            # the v4.5.17 audit. If this throws, every subsequent arbitrage
            # status sensor reading is stale; user can't tell anything's wrong
            # without DB inspection. Escalate to WARNING + exc_info.
            _LOGGER.warning(
                "Arbitrage status cache refresh failed — sensors will read "
                "stale until next successful refresh",
                exc_info=True,
            )

    @property
    def arbitrage_status(self) -> dict[str, Any]:
        """v4.3.0 D4: Cached savings rollup for sensor consumption.

        Refreshed each decision tick. Empty {} until first refresh.
        """
        return dict(self._arbitrage_status_cache)

    @property
    def arbitrage_round_trip_efficiency(self) -> float:
        """RTE assumption used in savings math (constant for v4.3.0)."""
        return self._ARBITRAGE_RTE

    # =========================================================================
    # v3.11.0 C1: EVSE Battery Hold
    # =========================================================================

    def _is_any_evse_charging(self) -> bool:
        """Check if any EVSE is actively charging (power > threshold)."""
        for evse_id in self._ev._evse:
            state = self._ev._get_evse_state(evse_id)
            if state.get("charging", False):
                return True
        return False

    def _apply_evse_battery_hold(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Override battery reserve to captured SOC when EVSEs are charging.

        Uses the SOC captured at hold start to prevent ratchet-down effect
        where each cycle locks to progressively lower SOC.
        """
        # Use captured SOC from hold start, fall back to current SOC
        hold_reserve = self._evse_hold_soc
        if hold_reserve is None:
            soc = decision.get("soc")
            if soc is None:
                return decision
            hold_reserve = int(soc)

        # Copy decision to avoid mutating BatteryStrategy's internal state
        decision = {**decision, "actions": list(decision.get("actions", []))}
        decision["reason"] = decision["reason"] + " + EVSE hold"

        # Use the battery strategy's configured reserve entity for reliable matching
        from .energy_const import DEFAULT_RESERVE_SOC_ENTITY
        reserve_entity = self._battery._get_entity(
            "reserve_soc_number", DEFAULT_RESERVE_SOC_ENTITY
        )

        # Update existing reserve action or add new one
        for i, action in enumerate(decision["actions"]):
            if action.get("target", "") == reserve_entity:
                decision["actions"][i] = {**action, "data": {"value": hold_reserve}}
                return decision

        # No reserve action yet — add one using configured entity
        decision["actions"].append({
            "service": "number.set_value",
            "target": reserve_entity,
            "data": {"value": hold_reserve},
        })
        return decision

    async def _async_decision_cycle(self, _now=None) -> None:
        """Run the periodic decision cycle (every N minutes)."""
        if not self._enabled:
            return

        self._maybe_reset_daily()

        try:
            # Get current TOU state
            period = self._tou.get_current_period()
            season = self._tou.get_season()

            # Check for period transition
            new_period = self._tou.check_period_transition()
            if new_period:
                self._tou_transition_count += 1
                # v4.6.9 D3: TOU transition is a user-visible decision event.
                self._record_decision(
                    action=f"tou_transition_{new_period}",
                    reason=f"TOU period changed to {new_period}",
                    target_entity=None,
                )
                # v3.13.3: Track SOC at peak start for battery degradation detection
                if new_period == "peak":
                    soc = self._battery.battery_soc
                    if soc is not None:
                        self._soc_at_peak_baseline.update(float(soc))

            # Battery decision — v4.5.0 D1: pass `now` for charge-window math
            # and `tou_transition_into` so chunk-lock resets on entry to off_peak.
            from homeassistant.util import dt as dt_util
            decision = self._battery.determine_mode(
                period, season,
                now=dt_util.now(),
                tou_transition_into=new_period,
            )

            # v4.3.0 D4: Arbitrage cycle accounting — fire-and-forget DB write.
            # When arbitrage_active and SOC has risen since the previous cycle,
            # log a row capturing the kWh charged this cycle and the savings vs.
            # the displaced-rate counterfactual (peak in summer, mid_peak in
            # shoulder/winter). Executed BEFORE actions so we measure the
            # state-as-observed, not state-after-control.
            try:
                await self._account_arbitrage_cycle(decision, period, season)
                await self._refresh_arbitrage_status_cache()
            except Exception:  # never let accounting break the cycle
                # v4.5.20: was debug — HIGH-severity periodic-closure shape.
                # This is the exact function signature the v4.5.17 NameError
                # lived in. A failure here silently breaks arbitrage savings
                # accounting; user-visible only via savings sensor reading
                # zero/stale for weeks. Escalate to WARNING + exc_info.
                _LOGGER.warning(
                    "Arbitrage cycle accounting skipped — savings sensors "
                    "may not reflect this cycle's activity",
                    exc_info=True,
                )

            # C1: EVSE battery hold — if any EVSE is charging, override battery
            # reserve to captured SOC so battery doesn't discharge to cover EV load.
            # Capture SOC once when hold starts to avoid ratchet-down effect.
            if self._is_any_evse_charging():
                if not self._evse_battery_hold_active:
                    # First cycle detecting EVSE charge — capture SOC
                    soc = decision.get("soc")
                    self._evse_hold_soc = int(soc) if soc is not None else None
                decision = self._apply_evse_battery_hold(decision)
                self._evse_battery_hold_active = True
            else:
                self._evse_battery_hold_active = False
                self._evse_hold_soc = None

            # Add EVSE hold status to decision for sensor visibility
            decision["evse_battery_hold"] = self._evse_battery_hold_active

            self._last_battery_decision = decision

            # v4.6.9 D3: Record battery strategy decision in the ring buffer.
            # Only record when the mode has actions (non-trivial decision) or
            # when EVSE hold is active — avoids flooding the buffer with idle cycles.
            _bat_actions = decision.get("actions", [])
            if _bat_actions or decision.get("evse_battery_hold"):
                _bat_target: str | None = (
                    _bat_actions[0].get("target") if _bat_actions else None
                )
                self._record_decision(
                    action=f"battery_{decision.get('mode', 'unknown')}",
                    reason=decision.get("reason", ""),
                    target_entity=_bat_target,
                )

            # v4.7.6 fix-up B-M3: snapshot the runtime-mutable EV thresholds
            # once at the start of the actuation block. `_fill_priority_soc`
            # has a sync setter (FillPrioritySOCNumber.async_set_native_value
            # → set_fill_priority_soc) that can land between reads inside
            # this tick. Without a snapshot, the drain branch and the fill
            # priority branch (and the NM trip message) could each observe a
            # different value within the same tick.
            #
            # v4.7.6.1 D1: snapshot _excess_solar_soc too — same race now
            # that ExcessSolarSOCNumber.async_set_native_value can land
            # between the excess-solar branch read at line ~2192 and any
            # downstream readers. Mirrors the B-M3 fix exactly.
            fill_priority_soc_tick = int(self._fill_priority_soc)
            excess_solar_soc_tick = int(self._excess_solar_soc)

            # Execute actions (skipped in observation mode)
            if not self._observation_mode:
                for action_spec in decision.get("actions", []):
                    await self._execute_service_action(action_spec)

                # E2: Pool optimization
                pool_actions = self._pool.determine_actions(period)
                for action_spec in pool_actions:
                    await self._execute_service_action(action_spec)

                # E2: EV charger control (v4.2.10: gated by toggle)
                if self._ev_tou_enabled:
                    ev_actions = self._ev.determine_actions(period)
                    for action_spec in ev_actions:
                        await self._execute_service_action(action_spec)

                # v4.5.0 D4: arbitrage / EV mutual-exclusion (compound-load
                # protection). Pauses any active EVSE while battery is
                # grid-charging via arbitrage CHARGE phase. Resumes when
                # phase exits CHARGE (HOLD or DISCHARGE) subject to TOU
                # period and other pause-reason precedence.
                # Cycle EC/HC reboot pickup: ATTAIN phase intentionally
                # EXCLUDED from this gate. Per operator decision 2026-06-12,
                # v1 attainability is observe-only on EVs — it reads the
                # consequence of EV ensure-on (net rate < projection slope)
                # but does NOT signal EVSE back off. Adding ATTAIN here
                # would convert a v1 observe-only feature into an EVSE
                # coordination lever. Tracked as a future cycle (see ledger
                # backlog stub).
                from .energy_battery import ARBITRAGE_PHASE_CHARGE
                arbitrage_charging = (
                    decision.get("arbitrage_phase") == ARBITRAGE_PHASE_CHARGE
                )
                arb_actions = self._ev.determine_arbitrage_actions(
                    arbitrage_charging=arbitrage_charging,
                    tou_period=period,
                )
                for action_spec in arb_actions:
                    await self._execute_service_action(action_spec)

                # C2: Excess solar EVSE charging
                if self._excess_solar_enabled:
                    soc = self._battery.battery_soc
                    remaining = self._battery.solcast_remaining
                    # v4.7.6.1 D1: read tick-snapshot, not live attr — same
                    # race-mitigation pattern as fill_priority_soc_tick.
                    excess_actions = self._ev.determine_excess_solar_actions(
                        soc, remaining, period,
                        soc_threshold=excess_solar_soc_tick,
                        kwh_threshold=self._excess_solar_kwh,
                    )
                    for action_spec in excess_actions:
                        await self._execute_service_action(action_spec)

                # v4.0.18: EV grid import cap
                if self._grid_import_cap_enabled:
                    # v4.5.0 unit-consistency: net_power_w normalizes
                    # firmware kW/W variants before the /1000 → kW step.
                    net_kw = (self._battery.net_power_w or 0) / 1000.0
                    grid_cap_actions = self._ev.determine_grid_cap_actions(
                        net_power_kw=net_kw,
                        grid_cap_kw=self._grid_import_cap_kw,
                        hysteresis_kw=DEFAULT_GRID_IMPORT_CAP_HYSTERESIS_KW,
                    )
                    for action_spec in grid_cap_actions:
                        await self._execute_service_action(action_spec)

                # v4.2.17: EV battery drain protection
                # v4.3.4 fix: pass battery_power_w (unit-normalized to W),
                # not battery_power (which is whatever the entity reports —
                # kW on newer Envoy installs, W on older ones). The drain
                # rule's `< -100` threshold is in W; passing kW broke the
                # comparison and silently disabled the protection.
                #
                # v4.7.6 D1: reserve_soc threaded through for the refined
                # `battery_out_of_capacity` resume gate.
                drain_actions = self._ev.determine_battery_drain_actions(
                    battery_power_w=self._battery.battery_power_w,
                    battery_soc=self._battery.battery_soc,
                    soc_threshold=self._ev_battery_drain_soc,
                    reserve_soc=getattr(self._battery, "reserve_soc", None),
                )
                for action_spec in drain_actions:
                    await self._execute_service_action(action_spec)

                # v4.7.6 D2: EV fill-priority pause (gated by excess_solar
                # switch — same toggle controls both turn-ON and pause sides).
                if self._excess_solar_enabled:
                    from .energy_const import DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH
                    # v4.7.6 fix-up B-M3: pass tick-snapshot, not live attr.
                    fp_actions = self._ev.determine_fill_priority_actions(
                        soc=self._battery.battery_soc,
                        remaining_forecast_kwh=self._battery.solcast_remaining,
                        tou_period=period,
                        soc_threshold=fill_priority_soc_tick,
                        excess_solar_kwh_threshold=self._excess_solar_kwh,
                        safety_margin_kwh=DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH,
                    )
                    for action_spec in fp_actions:
                        await self._execute_service_action(action_spec)
                    # v4.7.6 D4: NM trip on rising edge — first fill-priority
                    # pause per day. Gated by observation mode (Bug Class #23).
                    # v4.7.6 fix-up B-M3: pass tick-snapshot for the NM
                    # message so it agrees with the threshold used above.
                    await self._check_fill_priority_nm_trip(
                        fill_priority_soc_tick=fill_priority_soc_tick,
                    )

                # v4.2.19: EVSE power sensor health check
                evse_alerts = self._ev.check_power_sensor_health()
                for alert in evse_alerts:
                    await self._send_nm_alert(
                        title=f"EVSE Power Sensor Unavailable: {alert['evse_id']}",
                        message=alert["message"],
                        severity="high",
                        hazard_type="evse_sensor_offline",
                        location=alert["evse_id"],
                    )

                # E2: Smart plug control
                # v4.7.6 D6.1: gate L1 plug TOU under the same EVSE TOU
                # Management toggle as L2 EVSEs. L1 plugs are peer "small
                # EVSE" devices per the v4.7.6 user decision.
                if self._ev_tou_enabled:
                    plug_actions = self._smart_plugs.determine_actions(period)
                    for action_spec in plug_actions:
                        await self._execute_service_action(action_spec)

                # v4.2.21: Smart plug battery drain protection
                # v4.3.4 fix: same kW/W unit fix as EV drain above.
                # v4.7.6 D1 mirror: reserve_soc threaded through.
                # v4.7.6 fix-up A-H1: propagate Force-Charge state from EVPool
                # so plug pause rules respect the same admin override.
                force_charge_active = self._ev._is_force_charge_active()
                plug_drain_actions = self._smart_plugs.determine_battery_drain_actions(
                    battery_power_w=self._battery.battery_power_w,
                    battery_soc=self._battery.battery_soc,
                    soc_threshold=self._ev_battery_drain_soc,
                    reserve_soc=getattr(self._battery, "reserve_soc", None),
                    force_charge_active=force_charge_active,
                )
                for action_spec in plug_drain_actions:
                    await self._execute_service_action(action_spec)

                # v4.7.6 D2 mirror: L1 plug fill-priority pause
                if self._excess_solar_enabled:
                    from .energy_const import DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH
                    # v4.7.6 fix-up B-M3: same tick-snapshot used for L2 EV
                    # so L2 and L1 evaluate against the same threshold.
                    plug_fp_actions = self._smart_plugs.determine_fill_priority_actions(
                        soc=self._battery.battery_soc,
                        remaining_forecast_kwh=self._battery.solcast_remaining,
                        tou_period=period,
                        soc_threshold=fill_priority_soc_tick,
                        excess_solar_kwh_threshold=self._excess_solar_kwh,
                        safety_margin_kwh=DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH,
                        force_charge_active=force_charge_active,
                    )
                    for action_spec in plug_fp_actions:
                        await self._execute_service_action(action_spec)

            # E3: Circuit anomaly checks
            circuit_anomalies = self._circuits.check_anomalies()
            for anomaly in circuit_anomalies:
                anomaly_type = anomaly.get("type", "tripped_breaker")
                # v3.16: Tripped breaker alerts are HIGH, not CRITICAL.
                # CRITICAL bypasses all NM filters including the kill switch.
                # Only generator alerts (power outage) warrant CRITICAL.
                if anomaly_type == "tripped_breaker":
                    sev = "high"
                    title = f"Tripped Breaker: {anomaly.get('circuit', 'Unknown')}"
                    msg = (
                        f"Possible tripped breaker on {anomaly.get('circuit')} "
                        f"({anomaly.get('panel')} panel) — zero power for "
                        f"{anomaly.get('zero_duration_seconds', 0)}s"
                    )
                else:
                    sev = "medium"
                    title = f"Circuit Anomaly: {anomaly.get('circuit', 'Unknown')}"
                    msg = (
                        f"Unusual consumption on {anomaly.get('circuit')} "
                        f"({anomaly.get('panel')} panel) — {anomaly.get('power', 0):.0f}W "
                        f"(z={anomaly.get('z_score', 0):.1f}, "
                        f"baseline={anomaly.get('baseline_mean', 0):.0f}W)"
                    )
                await self._send_nm_alert(
                    title=title,
                    message=msg,
                    severity=sev,
                    hazard_type="circuit_anomaly",
                    location=anomaly.get("circuit", ""),
                )
                # v4.6.3 D4/D11/D12: Emit canonical AnomalyEvent for circuit
                # anomalies alongside existing SIGNAL_SAFETY_HAZARD dispatch.
                await self._emit_circuit_anomaly_event(anomaly)

            # E3: Generator alerts
            gen_alerts = self._generator.check_alerts()
            for alert in gen_alerts:
                await self._send_nm_alert(
                    title="Generator Running",
                    message=alert.get("message", "Generator status change"),
                    severity=alert.get("severity", "high"),
                    hazard_type="generator",
                    location="generator",
                )

            # E4: Cost accumulation
            self._billing.accumulate()

            # E5: Daily prediction (generates once per day, no-ops after)
            self._predictor.generate_prediction()

            # E5: Sunrise refresh (re-predict with fresh Solcast after sunrise)
            self._predictor.refresh_at_sunrise()

            # v4.1.1 B4 L2: Update room power profiles from room coordinator data
            self._update_power_profiles()

            # E6: Fetch forecast temps (async service call, cached for property)
            await self._update_forecast_temps()

            # E6: Load shedding evaluation (before constraint so shed level is current)
            if not self._observation_mode:
                self._update_load_shedding(period)

            # Persist peak import history hourly (independent of observation mode)
            from homeassistant.util import dt as dt_util
            current_hour = dt_util.now().hour
            if (
                self._peak_import_dirty
                and current_hour != self._last_peak_save_hour
                and self._peak_import_history
            ):
                self._last_peak_save_hour = current_hour
                self._peak_import_dirty = False
                await self._save_peak_import_history()

            # v4.1.1 B4 L2: Persist power profiles hourly
            if current_hour != getattr(self, "_last_profile_save_hour", -1):
                self._last_profile_save_hour = current_hour
                await self._save_power_profiles()

            # v4.7.1 Cycle B: Dynamic Preset Override Source evaluation
            # Runs after forecast update (needs WPM cached forecast).
            # Gated by observation_mode on the actuation side (Bug #23 — eval always runs).
            await self._async_evaluate_dynamic_presets()

            # E6: HVAC constraint determination
            self._update_hvac_constraint(period)

            # E6: Energy situation assessment
            self._update_energy_situation(period)

            # Envoy availability tracking
            self._track_envoy_availability(decision)

            # Cross-check consumption tracking (hourly, when data available)
            self._crosscheck_consumption()

            # v3.11.0 D1/D2: Log energy history + external conditions every 3rd cycle (~15min)
            # v3.15.0: Also saves envoy cache + midnight snapshot (serialized)
            self._cycle_count += 1
            if self._cycle_count % 3 == 0:
                # Serialize DB writes to avoid SQLite contention
                self.hass.async_create_task(
                    self._periodic_db_writes(decision)
                )

            # Notify energy sensors to refresh
            from homeassistant.helpers.dispatcher import async_dispatcher_send as _send
            from .signals import SIGNAL_ENERGY_ENTITIES_UPDATE
            _send(self.hass, SIGNAL_ENERGY_ENTITIES_UPDATE)

            _LOGGER.debug(
                "Energy cycle: period=%s, battery=%s (%s), soc=%s%%, pool=%s, envoy=%s",
                period,
                decision["mode"],
                decision["reason"],
                decision.get("soc"),
                self._pool.state,
                "ok" if decision.get("envoy_available", True) else "OFFLINE",
            )
        except Exception:
            _LOGGER.exception("Error in energy decision cycle")

    async def _evaluate_battery(self) -> list[CoordinatorAction]:
        """Evaluate battery strategy and return actions."""
        period = self._tou.get_current_period()
        season = self._tou.get_season()
        from homeassistant.util import dt as dt_util
        decision = self._battery.determine_mode(period, season, now=dt_util.now())

        # C1 fix: Apply EVSE battery hold in evaluate path too (not just timer path)
        if self._is_any_evse_charging():
            if not self._evse_battery_hold_active:
                soc = decision.get("soc")
                self._evse_hold_soc = int(soc) if soc is not None else None
            decision = self._apply_evse_battery_hold(decision)
            self._evse_battery_hold_active = True
        else:
            self._evse_battery_hold_active = False
            self._evse_hold_soc = None
        decision["evse_battery_hold"] = self._evse_battery_hold_active

        self._last_battery_decision = decision

        actions: list[CoordinatorAction] = []
        for action_spec in decision.get("actions", []):
            target = action_spec.get("target", "")
            service = action_spec.get("service", "")
            data = action_spec.get("data", {})

            if "entity_id" not in data and target:
                data = {**data, "entity_id": target}

            actions.append(
                ServiceCallAction(
                    coordinator_id="energy",
                    target_device=target,
                    severity=Severity.MEDIUM,
                    confidence=0.9,
                    description=f"Battery: {decision['reason']}",
                    service=service,
                    service_data=data,
                )
            )

        return actions

    async def _execute_service_action(self, action_spec: dict[str, Any]) -> None:
        """Execute a single battery service call."""
        service = action_spec.get("service", "")
        target = action_spec.get("target", "")
        data = action_spec.get("data", {})

        if not service:
            return

        try:
            if "." not in service:
                _LOGGER.warning("Energy: malformed service string: %s", service)
                return
            domain, svc = service.split(".", 1)
            svc_data = {**data}
            if target and "entity_id" not in svc_data:
                svc_data["entity_id"] = target

            await self.hass.services.async_call(domain, svc, svc_data, blocking=True)
            _LOGGER.info("Energy: executed %s on %s", service, target)
        except Exception:
            _LOGGER.exception("Energy: failed to execute %s on %s", service, target)

    def _get_active_weather_entity(self) -> str | None:
        """Return the active weather entity ID.

        v4.7.x Cycle A: Prefers WeatherProviderManager.active_provider;
        falls back to self._weather_entity (legacy CONF_ENERGY_WEATHER_ENTITY).
        """
        try:
            from ..const import DOMAIN as _DOMAIN_KEY
            weather_mgr = self.hass.data.get(_DOMAIN_KEY, {}).get("weather_manager")
            if weather_mgr is not None:
                active = weather_mgr.active_provider
                if active:
                    return active
        except Exception:
            pass
        return self._weather_entity or None

    async def _update_forecast_temps(self) -> None:
        """Fetch daily forecast high/low via weather.get_forecasts service.

        v4.7.x Cycle A: Routes through WeatherProviderManager when available,
        falling back to the legacy single-provider path for back-compat.
        Caches results in _cached_forecast_high/_cached_forecast_low +
        _cached_apparent_forecast_high.
        Modern HA (2024.3+) removed forecast from weather entity attributes.
        """
        # v4.7.x: Try WeatherProviderManager first (A4 migration)
        try:
            from ..const import DOMAIN as _DOMAIN_KEY
            weather_mgr = self.hass.data.get(_DOMAIN_KEY, {}).get("weather_manager")
        except Exception:
            weather_mgr = None

        if weather_mgr is not None:
            try:
                forecast = await weather_mgr.get_today_forecast()
                if forecast is not None:
                    if forecast.raw_high is not None:
                        self._cached_forecast_high = forecast.raw_high
                    if forecast.raw_low is not None:
                        self._cached_forecast_low = forecast.raw_low
                    # Cache apparent high separately for EnergyConstraint payload
                    self._cached_apparent_forecast_high = forecast.apparent_high
                    _LOGGER.debug(
                        "Forecast temps via WeatherProviderManager: "
                        "raw_high=%s raw_low=%s apparent_high=%s provider=%s",
                        self._cached_forecast_high,
                        self._cached_forecast_low,
                        self._cached_apparent_forecast_high,
                        forecast.provider_id,
                    )
                    return
            except Exception as exc:
                _LOGGER.warning(
                    "WeatherProviderManager.get_today_forecast failed, "
                    "falling back to legacy path: %s", exc
                )

        # Legacy path: direct hass.services.async_call using predictor's weather entity
        weather_eid = None
        if self._predictor:
            weather_eid = getattr(self._predictor, "_weather_entity", None)
        if not weather_eid:
            return

        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": weather_eid, "type": "daily"},
                blocking=True,
                return_response=True,
            )
            if not response:
                _LOGGER.warning("Forecast service returned empty response for %s", weather_eid)
                return
            if weather_eid not in response:
                _LOGGER.warning(
                    "Forecast response missing key %s, got keys: %s",
                    weather_eid, list(response.keys()),
                )
                return
            forecasts = response[weather_eid].get("forecast", [])
            if forecasts and isinstance(forecasts, list) and len(forecasts) > 0:
                today = forecasts[0]
                th = today.get("temperature")
                if th is not None:
                    try:
                        self._cached_forecast_high = float(th)
                    except (ValueError, TypeError):
                        pass
                tl = today.get("templow")
                if tl is not None:
                    try:
                        self._cached_forecast_low = float(tl)
                    except (ValueError, TypeError):
                        pass
                _LOGGER.debug(
                    "Forecast temps: high=%s low=%s from %s",
                    self._cached_forecast_high, self._cached_forecast_low, weather_eid,
                )
        except Exception as exc:
            _LOGGER.warning("Failed to fetch weather forecast for %s: %s", weather_eid, exc)

    async def _async_evaluate_dynamic_presets(self) -> None:
        """Evaluate dynamic-preset overrides for all opted-in canonical HVAC zones.

        v4.7.1 Cycle B: Called once per EC decision tick (5-min cadence).
        Evaluation always runs (even in observation mode — Bug #23: gate is on actuation side).
        Results stored in self._dynamic_preset_overrides for sensor visibility.

        Does nothing when:
        - Master kill switch is OFF (CONF_DYNAMIC_PRESET_ENABLED=False)
        - WeatherProviderManager has no cached forecast
        """
        try:
            from ..const import DOMAIN as _DOMAIN_KEY, CONF_ENTRY_TYPE, ENTRY_TYPE_COORDINATOR_MANAGER
            from .energy_const import CONF_DYNAMIC_PRESET_DWELL_MINUTES, CONF_DYNAMIC_PRESET_HYSTERESIS_F

            # Read master enable from EC attribute (mirrors how other EC sub-switches work)
            if not self._dynamic_preset_enabled:
                _LOGGER.debug("DynamicPreset: master switch OFF — skipping evaluation")
                return

            # Read current CM options for DynamicPresetOverrideSource config (Bug #14)
            cm_options: dict = {}
            for entry in self.hass.config_entries.async_entries(_DOMAIN_KEY):
                if {**entry.data, **entry.options}.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    cm_options = {**entry.data, **entry.options}
                    break

            # Get WPM forecast availability (Bug #5 — defer if no forecast)
            weather_mgr = self.hass.data.get(_DOMAIN_KEY, {}).get("weather_manager")
            if weather_mgr is None:
                _LOGGER.debug("DynamicPreset: no WeatherProviderManager — skipping")
                return
            apparent_high = weather_mgr.current_apparent_forecast_high()
            if apparent_high is None:
                _LOGGER.debug("DynamicPreset: no cached forecast — skipping")
                return

            # Get house_state for offset-reset check
            house_state = self._get_house_state()

            # Lazily instantiate DynamicPresetOverrideSource (avoids circular import).
            # Bug Class #45: use bound method _get_cm_options instead of
            # lambda: cm_options. The lambda would capture the local from the
            # FIRST call; subsequent calls would see stale config.
            if self._dynamic_preset_source is None:
                from .dynamic_preset import DynamicPresetOverrideSource
                self._dynamic_preset_source = DynamicPresetOverrideSource(
                    hass=self.hass,
                    get_options=self._get_cm_options,
                )

            # Enumerate opted-in canonical HVAC zones
            from .hvac_zones import iter_canonical_hvac_zones
            from ..const import ENTRY_TYPE_ZONE_MANAGER
            canonical_zones = iter_canonical_hvac_zones(self.hass)

            # Build zone_data lookup from Zone Manager entry
            zm_zones: dict = {}
            for entry in self.hass.config_entries.async_entries(_DOMAIN_KEY):
                merged = {**entry.data, **entry.options}
                if merged.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
                    zm_zones = merged.get("zones", {})
                    break

            updated_overrides: dict[str, list] = {}
            # v4.7.7 B2: per-zone skip reasons captured for sensor exposure.
            # Built per-tick; replaces the previous tick's snapshot.
            updated_skip_reasons: dict[str, str] = {}
            for zone_info in canonical_zones:
                zone_id = zone_info["zone_id"]
                zone_name = zone_info["zone_name"]

                # Get zone_data from Zone Manager.
                # v4.7.5 D3 Lazy Canonical Resolution (post-review M3+A-H3):
                # tightened 3-step resolution:
                #   1) Direct match on the raw zone_name (covers solo zones
                #      AND post-v4.7.5 mirrored siblings where any constituent
                #      key returns equivalent data).
                #   2) Merged canonical label — split on " + " and resolve to
                #      the first constituent that's present in zm_zones.
                #      Zone names containing " + " are rejected at
                #      config-flow validate time (see config_flow.py
                #      _ZONE_NAME_PLUS_SEPARATOR_RE), so a positive " + "
                #      check here cannot collide with a real zone name.
                #   3) Fallback on zone_id (legacy / migration paths only) —
                #      kept last so a zone literally named "zone_N" can't
                #      shadow a real canonical resolution.
                # See QUALITY_CONTEXT.md "Lazy Canonical Resolution".
                zone_data = zm_zones.get(zone_name)
                # v4.7.7 B2: track whether canonical resolution failed for
                # this zone so we can surface it as skip_reason later.
                _canonical_resolution_failed = False
                if not zone_data and " + " in zone_name:
                    parts = [p.strip() for p in zone_name.split(" + ")]
                    parts = [p for p in parts if p]
                    matched_parts = [p for p in parts if p in zm_zones]
                    if matched_parts:
                        zone_data = zm_zones[matched_parts[0]]
                    else:
                        _canonical_resolution_failed = True
                        _LOGGER.warning(
                            "DynamicPreset zone=%s: canonical-merged label "
                            "did not resolve to any known house zone "
                            "(parts=%s, zm_zones keys=%s); skipping DPM eval",
                            zone_name, parts, list(zm_zones.keys()),
                        )
                if not zone_data:
                    zone_data = zm_zones.get(zone_id, {})

                # Get delta for this zone from WPM
                try:
                    delta = weather_mgr.baseline_delta_for_zone(zone_id, "home")
                    baseline_high = None
                    if delta is not None and apparent_high is not None:
                        baseline_high = apparent_high - delta
                except Exception:
                    _LOGGER.debug("DynamicPreset zone=%s: delta computation failed", zone_id, exc_info=True)
                    delta = None
                    baseline_high = None

                try:
                    # v4.7.7 B2: use the reason-aware variant so we can
                    # surface why each zone was skipped in the
                    # `skipped_zones_with_reason` sensor attribute.
                    overrides, skip_reason = await (
                        self._dynamic_preset_source.async_evaluate_with_reason(
                            zone_id=zone_id,
                            zone_data=zone_data,
                            delta=delta,
                            house_state=house_state,
                            apparent_high=apparent_high,
                            baseline_high=baseline_high,
                        )
                    )
                    updated_overrides[zone_id] = overrides
                    if overrides:
                        _LOGGER.debug(
                            "DynamicPreset zone=%s: %d override(s) emitted (obs_mode=%s)",
                            zone_id, len(overrides), self._observation_mode,
                        )
                    else:
                        # v4.7.7 A-M1 fix-up: canonical_label_mismatch only
                        # takes precedence when canonical resolution failed
                        # AND the zone_id fallback at line 2723-2724 also
                        # returned empty data. If the fallback succeeded
                        # with non-empty zone_data, the downstream eval ran
                        # against real data and its skip_reason (e.g.,
                        # dwell_pending, home_range_not_configured) is the
                        # legitimate cause — overwriting it with
                        # canonical_label_mismatch would mislead diagnosis.
                        reason = (
                            "canonical_label_mismatch"
                            if _canonical_resolution_failed and not zone_data
                            else skip_reason
                        )
                        if reason:
                            updated_skip_reasons[zone_id] = reason
                except Exception:
                    _LOGGER.warning("DynamicPreset zone=%s: evaluation failed", zone_id, exc_info=True)
                    updated_overrides.setdefault(zone_id, [])
                    updated_skip_reasons[zone_id] = "evaluation_failed"

            # HIGH B3: Only dispatch if overrides actually changed (prevent 864
            # redundant state-writes/day when no bucket has transitioned).
            _prev = self._dynamic_preset_overrides
            self._dynamic_preset_overrides = updated_overrides
            # v4.7.7 B2: persist the per-tick skip reasons so the sensor
            # extra_state_attributes can read them on demand. Replaces the
            # previous tick's snapshot wholesale (no per-zone merge).
            self._dynamic_preset_skip_reasons = updated_skip_reasons

            _changed = set(updated_overrides.keys()) != set(_prev.keys())
            if not _changed:
                for zid, new_ovs in updated_overrides.items():
                    old_ovs = _prev.get(zid, [])
                    if len(new_ovs) != len(old_ovs):
                        _changed = True
                        break
                    for n, o in zip(new_ovs, old_ovs):
                        if (n.cool_low != o.cool_low or n.cool_high != o.cool_high
                                or n.preset != o.preset):
                            _changed = True
                            break
                    if _changed:
                        break

            if _changed:
                try:
                    from homeassistant.helpers.dispatcher import async_dispatcher_send
                    from .signals import SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED
                    async_dispatcher_send(self.hass, SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED)
                except Exception:
                    pass

            # v4.7.9 D2: independent edge detection on the skip_reasons dict.
            # Captures the case where the overrides dict stayed empty between
            # ticks but skip_reason values transitioned (e.g.,
            # dwell_pending -> unknown_bucket for the same zone). Sensor
            # subscribes to BOTH signals; double-fire on tick that mutates
            # both dicts is harmless (sensor's _on_signal is idempotent
            # async_write_ha_state). Bug Class #45 safe — no lambda closure
            # over loop vars; bound module-level dispatcher call.
            _reasons_changed = (
                self._dynamic_preset_skip_reasons_prev != updated_skip_reasons
            )
            # Snapshot AFTER comparison so the next tick's compare is correct.
            # v4.7.9 B-M1 fix-up: skip the dict() copy on no-change ticks
            # (cosmetic CPU/GC saving — the prev snapshot already equals
            # updated_skip_reasons). The copy is required when changed so we
            # don't capture the same reference we assigned to
            # self._dynamic_preset_skip_reasons above.
            if _reasons_changed:
                self._dynamic_preset_skip_reasons_prev = dict(updated_skip_reasons)
                try:
                    from homeassistant.helpers.dispatcher import async_dispatcher_send
                    from .signals import SIGNAL_DPM_SKIP_REASONS_UPDATED
                    async_dispatcher_send(self.hass, SIGNAL_DPM_SKIP_REASONS_UPDATED)
                except Exception as e:
                    # v4.7.9 B-L2 fix-up: log dispatch failures instead of
                    # silently swallowing — silent except masks real wiring
                    # bugs (import path, dispatcher init order).
                    _LOGGER.warning(
                        "DPM skip-reasons signal dispatch failed: %s", e,
                    )

        except Exception:
            _LOGGER.warning("DynamicPreset: _async_evaluate_dynamic_presets failed", exc_info=True)

    def _get_cm_options(self) -> dict:
        """Return current Coordinator Manager options, re-read on every call.

        v4.7.1 fix-up: Bug Class #45 — replaces the stale lambda that captured
        cm_options from the first evaluate tick. This method is passed as
        get_options to DynamicPresetOverrideSource so every evaluate_and_emit
        call reads fresh CONF values (dwell, hysteresis, bucket boundaries).
        """
        try:
            from ..const import DOMAIN as _DOMAIN_KEY, CONF_ENTRY_TYPE, ENTRY_TYPE_COORDINATOR_MANAGER
            for entry in self.hass.config_entries.async_entries(_DOMAIN_KEY):
                if {**entry.data, **entry.options}.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    return {**entry.data, **entry.options}
            return {}
        except Exception:
            return {}

    def _get_house_state(self) -> str:
        """Return current house_state string from presence coordinator (or empty string)."""
        try:
            from ..const import DOMAIN as _DOMAIN_KEY
            manager = self.hass.data.get(_DOMAIN_KEY, {}).get("coordinator_manager")
            if manager is None:
                return ""
            presence = manager.coordinators.get("presence")
            if presence is None:
                return ""
            return str(getattr(presence, "_house_state", ""))
        except Exception:
            return ""

    def _update_hvac_constraint(self, tou_period: str) -> None:
        """Determine HVAC constraint mode based on TOU, SOC, weather, and import.

        v3.9.0-E6: Full implementation with configurable offsets, pre_heat, shed,
        max_runtime_minutes, and auto-learned load shedding threshold.
        """
        soc = self._battery.battery_soc or 0
        solar_class = self._battery.classify_solar_day()
        reason = ""
        forecast_high = self._cached_forecast_high
        forecast_low = self._cached_forecast_low

        # HVAC post-peak coast release — mirror of the v4.7.29 battery fix.
        # Summer mid_peak is a bracketed period (pre-peak / peak / post-peak).
        # Coasting is correct PRE-peak (let temp drift to save before the
        # expensive peak) but wasteful POST-peak: off_peak is imminent (cheap
        # cooling) and the battery is discharging (v4.7.29), so release to normal
        # and let comfort recover. Shoulder/winter mid_peak IS the top rate
        # (no peak is ever ahead), so they must keep coasting — hence the
        # season gate. Short-circuits on non-mid_peak so the hour-walk only
        # runs when relevant.
        summer_post_peak_midpeak = (
            tou_period == "mid_peak"
            and self._tou.get_season() == "summer"
            and not self._tou.peak_ahead_before_offpeak()
        )

        # Determine constraint mode (priority order: shed > coast > pre_cool > pre_heat > normal)
        if (
            tou_period == "peak"
            and soc < 20
            and self._load_shedding_enabled
            and self._load_shedding_active_level > 0
        ):
            self._hvac_constraint_mode = "shed"
            self._hvac_constraint_offset = self._constraint_shed_offset
            reason = f"peak TOU, low SOC ({soc}%), active load shedding"
        elif tou_period == "peak":
            self._hvac_constraint_mode = "coast"
            self._hvac_constraint_offset = self._constraint_coast_offset
            reason = "peak TOU period"
        elif (
            tou_period == "mid_peak"
            and solar_class in ("poor", "very_poor")
            and not summer_post_peak_midpeak
        ):
            self._hvac_constraint_mode = "coast"
            self._hvac_constraint_offset = self._constraint_coast_offset - 1.0
            reason = "mid-peak poor solar"
        elif (
            tou_period == "off_peak"
            and soc < 50
            and solar_class in ("excellent", "good")
        ):
            self._hvac_constraint_mode = "pre_cool"
            self._hvac_constraint_offset = self._constraint_precool_offset
            reason = "off-peak pre-cool (low SOC, good solar)"
        elif (
            tou_period == "off_peak"
            and forecast_low is not None
            and forecast_low < self._preheat_temp_threshold
            and soc > 50
        ):
            self._hvac_constraint_mode = "pre_heat"
            self._hvac_constraint_offset = self._constraint_preheat_offset
            reason = f"off-peak pre-heat (forecast low {forecast_low:.0f}F < {self._preheat_temp_threshold:.0f}F)"
        else:
            self._hvac_constraint_mode = "normal"
            self._hvac_constraint_offset = 0.0
            reason = "normal conditions"

        self._hvac_constraint_reason = reason

        # Compute max_runtime_minutes from time remaining in current period
        max_runtime = None
        if self._hvac_constraint_mode in ("coast", "shed"):
            transition = self._tou.get_next_transition()
            hours_until = transition.get("hours_until", 0)
            max_runtime = int(hours_until * 60)

        # Fire dispatcher signal on constraint change
        constraint_key = (
            f"{self._hvac_constraint_mode}:{self._hvac_constraint_offset}:{max_runtime}"
        )
        if constraint_key != self._last_published_constraint:
            self._last_published_constraint = constraint_key
            # v4.6.9 D3: Record HVAC constraint change in decision buffer.
            self._record_decision(
                action=f"hvac_constraint_{self._hvac_constraint_mode}",
                reason=reason,
                target_entity=None,
            )
            from .signals import EnergyConstraint, SIGNAL_ENERGY_CONSTRAINT
            from homeassistant.helpers.dispatcher import async_dispatcher_send

            constraint = EnergyConstraint(
                mode=self._hvac_constraint_mode,
                setpoint_offset=self._hvac_constraint_offset,
                occupied_only=True,
                max_runtime_minutes=max_runtime,
                fan_assist=(self._hvac_constraint_mode in ("coast", "shed")),
                reason=reason,
                solar_class=solar_class,
                forecast_high_temp=forecast_high,
                soc=soc if soc > 0 else None,
                # v4.7.x Cycle A: apparent-temp alongside raw_high (Bug #37 — additive)
                apparent_forecast_high_temp=self._cached_apparent_forecast_high,
            )
            async_dispatcher_send(
                self.hass, SIGNAL_ENERGY_CONSTRAINT, constraint
            )
            _LOGGER.info(
                "Energy: Published HVAC constraint mode=%s offset=%.1f "
                "max_runtime=%s reason=%s",
                self._hvac_constraint_mode,
                self._hvac_constraint_offset,
                max_runtime,
                reason,
            )

    def _update_energy_situation(self, tou_period: str) -> None:
        """Assess overall energy situation."""
        if self.load_shedding_active:
            self._energy_situation = "constrained"
        elif tou_period == "peak":
            self._energy_situation = "optimizing"
        elif tou_period == "mid_peak":
            self._energy_situation = "optimizing"
        else:
            self._energy_situation = "normal"

    def _update_load_shedding(self, tou_period: str) -> None:
        """Evaluate and cascade load shedding based on sustained grid import.

        v3.9.0-E6: Monitors grid import during peak/mid-peak. When sustained
        import exceeds threshold for configured duration, progressively sheds
        loads in priority order: pool -> EV -> smart_plugs -> hvac (coast).

        Threshold auto-learns from historical 90th percentile peak import
        after 30 days of data.
        """
        if not self._load_shedding_enabled:
            self._load_shedding_active_level = 0
            self._sustained_import_readings.clear()
            return

        # Only shed during peak and mid-peak
        if tou_period not in ("peak", "mid_peak"):
            if self._load_shedding_active_level > 0:
                _LOGGER.info("Energy: Load shedding released (off-peak)")
            self._load_shedding_active_level = 0
            self._sustained_import_readings.clear()
            return

        # Read current grid import
        # v4.5.0 unit-consistency: use net_power_w which normalizes
        # firmware kW/W variants. Pre-v4.5.0, the raw `net_power` divided
        # by 1000 silently broke load-shedding thresholding when Envoy
        # firmware reported in kW.
        #
        # M6 (Pass-2 P2B-HIGH-1): exclude the battery's own grid-charge
        # power from the load-shedding import reading. D1b attain may
        # charge during mid_peak (state-matrix invariant change); the
        # ~16 kW battery draw would otherwise trip load shedding to
        # shed pool/EV/plugs/HVAC even though the actual house+EV draw is
        # under threshold. Reuse the same battery-exclusion math the
        # attainability grid-import guard uses (max(0, battery_power)).
        snap = self._battery._effective_import_kw()
        if snap is None:
            return
        # snap = (effective_kw, net_kw, battery_charge_kw). Use effective
        # — net minus battery charge — clamped at 0.
        effective_kw, _net_kw, _batt_charge_kw = snap
        import_kw = max(effective_kw, 0.0)

        # Record for history (auto-learning)
        if tou_period == "peak" and import_kw > 0:
            self._peak_import_history.append(import_kw)
            self._peak_import_dirty = True
            # v3.13.2: Feed MetricBaseline for z-score threshold
            self._peak_import_baseline.update(import_kw)
            # Keep 30 days worth (at 5-min intervals during 4hr peak = ~48/day * 30)
            if len(self._peak_import_history) > 1500:
                self._peak_import_history = self._peak_import_history[-1500:]

        # Determine effective threshold
        threshold = self._get_effective_shedding_threshold()

        # Track sustained import
        self._sustained_import_readings.append(import_kw)
        readings_needed = max(
            1,
            self._load_shedding_sustained_minutes // self._decision_interval,
        )
        # Keep only the window we need
        if len(self._sustained_import_readings) > readings_needed:
            self._sustained_import_readings = self._sustained_import_readings[
                -readings_needed:
            ]

        # Check if sustained: all readings in window exceed threshold
        if len(self._sustained_import_readings) >= readings_needed:
            sustained = all(
                r >= threshold for r in self._sustained_import_readings
            )
        else:
            sustained = False

        if sustained and self._load_shedding_active_level < len(LOAD_SHEDDING_PRIORITY):
            # Escalate one level
            self._load_shedding_active_level += 1
            shed_target = LOAD_SHEDDING_PRIORITY[self._load_shedding_active_level - 1]
            _LOGGER.warning(
                "Energy: Load shedding escalated to level %d — shedding %s "
                "(sustained import %.1f kW > threshold %.1f kW for %d min)",
                self._load_shedding_active_level,
                shed_target,
                import_kw,
                threshold,
                self._load_shedding_sustained_minutes,
            )
            # Execute the actual shed action
            self._execute_shed_action(shed_target, activate=True)
            # v4.6.9 D3: Record load shedding escalation in decision buffer.
            self._record_decision(
                action="load_shed_escalate",
                reason=(
                    f"Load shedding escalated to level {self._load_shedding_active_level} "
                    f"(shedding {shed_target}, import {import_kw:.1f} kW > {threshold:.1f} kW)"
                ),
                target_entity=None,
            )
            # Activity log: load shedding escalation
            from ..const import DOMAIN
            activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
            if activity_logger:
                self.hass.async_create_task(
                    activity_logger.log(
                        coordinator="energy",
                        action="load_shed_escalate",
                        description=f"Load shedding escalated to level {self._load_shedding_active_level} (shedding {shed_target})",
                        importance="notable",
                        details={
                            "level": self._load_shedding_active_level,
                            "target": shed_target,
                            "import_kw": round(import_kw, 2),
                            "threshold_kw": round(threshold, 2),
                        },
                    )
                )
            # Clear readings to require another sustained window for next escalation
            self._sustained_import_readings.clear()
        elif (
            not sustained
            and self._load_shedding_active_level > 0
            and len(self._sustained_import_readings) >= readings_needed
        ):
            # v3.15.0: Grace period after restore — let readings buffer refill
            if self._load_shedding_grace_cycles > 0:
                self._load_shedding_grace_cycles -= 1
                return
            # Full window of below-threshold readings — de-escalate one level
            released = LOAD_SHEDDING_PRIORITY[self._load_shedding_active_level - 1]
            self._execute_shed_action(released, activate=False)
            self._load_shedding_active_level -= 1
            if self._load_shedding_active_level == 0:
                _LOGGER.info("Energy: Load shedding fully released")
            else:
                _LOGGER.info(
                    "Energy: Load shedding de-escalated to level %d (released %s)",
                    self._load_shedding_active_level, released,
                )
            # Activity log: load shedding de-escalation
            from ..const import DOMAIN
            activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
            if activity_logger:
                desc = (
                    "Load shedding fully released"
                    if self._load_shedding_active_level == 0
                    else f"Load shedding de-escalated to level {self._load_shedding_active_level} (released {released})"
                )
                self.hass.async_create_task(
                    activity_logger.log(
                        coordinator="energy",
                        action="load_shed_release",
                        description=desc,
                        importance="notable",
                        details={
                            "level": self._load_shedding_active_level,
                            "released": released,
                        },
                    )
                )

    def _execute_shed_action(self, target: str, activate: bool) -> None:
        """Execute or release a load shedding action for the given target.

        Uses the subsystem controllers' action pattern — generates service call
        specs and executes them through _execute_service_action.
        """
        actions: list[dict[str, Any]] = []

        if target == "pool":
            from .energy_pool import POOL_REDUCED_SPEED, POOL_STATE_REDUCED, POOL_STATE_NORMAL
            if activate:
                current = self._pool.current_speed
                if current is not None and current > POOL_REDUCED_SPEED:
                    if self._pool._original_speed is None:
                        self._pool._original_speed = current
                    actions.append({
                        "service": "number.set_value",
                        "target": self._pool._speed_entity,
                        "data": {"value": POOL_REDUCED_SPEED},
                    })
                    self._pool._state = POOL_STATE_REDUCED
            else:
                if self._pool._original_speed is not None:
                    actions.append({
                        "service": "number.set_value",
                        "target": self._pool._speed_entity,
                        "data": {"value": self._pool._original_speed},
                    })
                    self._pool._original_speed = None
                    self._pool._state = POOL_STATE_NORMAL
        elif target == "ev":
            for evse_id, config in self._ev._evse.items():
                switch_entity = config.get("switch", "")
                if not switch_entity:
                    continue
                if activate:
                    state = self._ev._get_evse_state(evse_id)
                    if state["is_on"] and evse_id not in self._ev._paused_by_us:
                        actions.append({
                            "service": "switch.turn_off",
                            "target": switch_entity,
                            "data": {},
                        })
                        self._ev._paused_by_us.add(evse_id)
                else:
                    if evse_id in self._ev._paused_by_us:
                        # v4.2.21: Don't resume if battery drain is active
                        if evse_id in self._ev._paused_by_battery_drain:
                            self._ev._paused_by_us.discard(evse_id)
                            continue
                        actions.append({
                            "service": "switch.turn_on",
                            "target": switch_entity,
                            "data": {},
                        })
                        self._ev._paused_by_us.discard(evse_id)
        elif target == "smart_plugs":
            for entity_id in self._smart_plugs._plugs:
                state = self.hass.states.get(entity_id)
                if state is None:
                    continue
                if activate:
                    if state.state == "on" and entity_id not in self._smart_plugs._paused_by_us:
                        actions.append({
                            "service": "switch.turn_off",
                            "target": entity_id,
                            "data": {},
                        })
                        self._smart_plugs._paused_by_us.add(entity_id)
                else:
                    if entity_id in self._smart_plugs._paused_by_us:
                        # v4.2.21: Don't resume if battery drain is active
                        if entity_id in self._smart_plugs._paused_by_battery_drain:
                            self._smart_plugs._paused_by_us.discard(entity_id)
                            continue
                        actions.append({
                            "service": "switch.turn_on",
                            "target": entity_id,
                            "data": {},
                        })
                        self._smart_plugs._paused_by_us.discard(entity_id)
        elif target == "hvac":
            # HVAC shedding is handled via the constraint signal (shed mode),
            # not by direct service calls. _update_hvac_constraint publishes
            # the shed constraint when _load_shedding_active_level > 0.
            pass

        for action_spec in actions:
            self.hass.async_create_task(self._execute_service_action(action_spec))
        if actions:
            _LOGGER.info(
                "Energy: Load shed %s — %s (%d actions)",
                "activated" if activate else "released", target, len(actions),
            )

    def _get_effective_shedding_threshold(self) -> float:
        """Return the effective load shedding threshold.

        v3.13.2: In 'auto' mode, uses MetricBaseline z-score (mean + 2*std)
        after 300+ samples (~5 hours of peak data). Falls back to 90th
        percentile with 30+ days, then fixed threshold.
        """
        if self._load_shedding_mode == LOAD_SHEDDING_MODE_AUTO:
            # Prefer z-score threshold (mean + 2*std) with enough baseline data
            if self._peak_import_baseline.sample_count >= 300:
                self._learned_threshold_kw = (
                    self._peak_import_baseline.mean + 2 * self._peak_import_baseline.std
                )
                return self._learned_threshold_kw
            # Fall back to 90th percentile with 30+ days of history
            if len(self._peak_import_history) >= LOAD_SHEDDING_AUTO_MIN_DAYS * 10:
                sorted_readings = sorted(self._peak_import_history)
                idx = int(len(sorted_readings) * LOAD_SHEDDING_AUTO_PERCENTILE / 100)
                self._learned_threshold_kw = sorted_readings[min(idx, len(sorted_readings) - 1)]
                return self._learned_threshold_kw
        return self._load_shedding_threshold_kw

    async def _send_nm_alert(
        self,
        title: str,
        message: str,
        severity: str = "high",
        hazard_type: str = "",
        location: str = "",
    ) -> None:
        """Send an alert through the Notification Manager."""
        from ..const import DOMAIN
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            _LOGGER.warning("Energy NM alert (no NM): %s — %s", title, message)
            return
        try:
            severity_map = {"low": Severity.LOW, "medium": Severity.MEDIUM,
                            "high": Severity.HIGH, "critical": Severity.CRITICAL}
            await nm.async_notify(
                coordinator_id="energy",
                severity=severity_map.get(severity, Severity.HIGH),
                title=title,
                message=message,
                hazard_type=hazard_type or None,
                location=location or None,
            )
        except Exception:
            # v4.5.20: was debug. Soft-escalate — NM alert failure means
            # operator may miss a notification, but core energy logic
            # continues. Warning + exc_info gives observability without
            # alarming on benign NM-not-loaded states.
            _LOGGER.warning(
                "Energy: NM alert failed (non-fatal): %s",
                title,
                exc_info=True,
            )

    async def _emit_circuit_anomaly_event(self, anomaly: dict) -> None:
        """Emit canonical AnomalyEvent for a circuit anomaly (D4 / D11 / D12).

        Called for each new circuit anomaly alongside the existing NM alert
        path. Never raises — exceptions are swallowed so energy processing
        continues unaffected.
        """
        try:
            from ..const import DOMAIN  # noqa: PLC0415
            from homeassistant.util import dt as dt_util  # noqa: PLC0415
            from .anomaly_event import (  # noqa: PLC0415
                AnomalyEvent,
                AnomalySeverity,
                AnomalyType,
                build_context_json,
            )

            # v4.7.12 D2: local renamed `anomaly_subtype` to avoid clashing
            # with the new ``AnomalyType`` import / ``anomaly_type`` kwarg.
            anomaly_subtype = anomaly.get("type", "tripped_breaker")
            circuit_name = anomaly.get("circuit", "unknown")
            entity_id = anomaly.get("entity_id")

            _ctx = build_context_json(
                source_signal="SIGNAL_SAFETY_HAZARD",
                extra={k: v for k, v in anomaly.items() if k != "entity_id"},
            )
            severity = (
                AnomalySeverity.CRITICAL
                if anomaly_subtype == "tripped_breaker"
                else AnomalySeverity.WARNING
            )
            _event = AnomalyEvent(
                coordinator="energy",
                type=f"energy.circuit_{anomaly_subtype}",
                severity=severity,
                anomaly_type=AnomalyType.POINT_IN_TIME,
                detected_at=dt_util.utcnow().isoformat(),
                payload=_ctx,
                entity_id=entity_id,
            )
            database = self.hass.data.get(DOMAIN, {}).get("database")
            if database is not None:
                await database.save_anomaly_event(_event)
                _LOGGER.info(
                    "Circuit anomaly event emitted: type=%s circuit=%s",
                    anomaly_subtype, circuit_name,
                )
            # D12: fire activity_logger (awaited — A5 fix: avoid untracked task)
            activity_logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
            if activity_logger:
                await activity_logger.log(
                    coordinator="energy",
                    action="anomaly",
                    description=(
                        f"Circuit {anomaly_subtype} on {circuit_name} "
                        f"z={anomaly.get('z_score', 0.0):.2f}"
                    ),
                    importance="critical" if anomaly_subtype == "tripped_breaker" else "notable",
                    entity_id=entity_id,
                    details={
                        "type": f"energy.circuit_{anomaly_subtype}",
                        "circuit": circuit_name,
                        "z_score": anomaly.get("z_score", 0.0),
                    },
                )
        except Exception:
            _LOGGER.debug("_emit_circuit_anomaly_event failed (swallowed)", exc_info=True)

    # =========================================================================
    # v3.13.1: DATA PIPELINE HELPERS
    # =========================================================================

    def _get_house_avg_climate(self) -> tuple[float | None, float | None]:
        """Return (house_avg_temp, house_avg_humidity) from room coordinators.

        Iterates room config entries and reads their temperature/humidity
        sensor states to compute whole-house averages.
        """
        from ..const import (
            DOMAIN, CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM,
            CONF_TEMPERATURE_SENSOR, CONF_HUMIDITY_SENSOR,
        )
        temps: list[float] = []
        humids: list[float] = []
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                config = {**entry.data, **entry.options}
                if config.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                # Temperature
                temp_entity = config.get(CONF_TEMPERATURE_SENSOR)
                if temp_entity:
                    state = self.hass.states.get(temp_entity)
                    if state and state.state not in ("unknown", "unavailable"):
                        try:
                            temps.append(float(state.state))
                        except (ValueError, TypeError):
                            pass
                # Humidity
                hum_entity = config.get(CONF_HUMIDITY_SENSOR)
                if hum_entity:
                    state = self.hass.states.get(hum_entity)
                    if state and state.state not in ("unknown", "unavailable"):
                        try:
                            humids.append(float(state.state))
                        except (ValueError, TypeError):
                            pass
        except Exception:
            # v4.5.20: was bare `pass`. Energy decision cycle calls this
            # every ~15 min; silent failure means house-climate context
            # missing from history snapshots with zero log signal.
            # Caller accepts (None, None) gracefully, so we still pass
            # but log first.
            _LOGGER.warning(
                "Energy: _get_house_avg_climate iteration failed — "
                "history snapshots will use None for climate",
                exc_info=True,
            )

        avg_temp = sum(temps) / len(temps) if temps else None
        avg_humidity = sum(humids) / len(humids) if humids else None
        return avg_temp, avg_humidity

    def _update_power_profiles(self) -> None:
        """Update room power profiles from room coordinator data."""
        from ..const import DOMAIN, STATE_POWER_CURRENT, STATE_OCCUPIED
        from ..coordinator import UniversalRoomCoordinator
        from homeassistant.util import dt as dt_util

        now = dt_util.now()
        time_bin = get_time_bin(now.hour)
        day_type = 1 if now.weekday() >= 5 else 0

        try:
            for key, value in self.hass.data.get(DOMAIN, {}).items():
                if not isinstance(value, UniversalRoomCoordinator):
                    continue
                coord_data = value.data
                if not coord_data:
                    continue

                room_id = value.entry.data.get("room_name", "unknown")
                power = coord_data.get(STATE_POWER_CURRENT, 0)
                is_occupied = coord_data.get(STATE_OCCUPIED, False)

                if power is not None and power >= 0:
                    self._power_profiles.update(
                        room_id, time_bin, day_type, float(power), is_occupied
                    )
        except Exception:
            # v4.5.20: was debug. Iterates hass.data registry — mutation
            # during iteration or coord-data shape changes can silently
            # halt B4 L2 power profile learning indefinitely. Escalate.
            _LOGGER.warning(
                "Power profile update error — B4 L2 learning skipped this cycle",
                exc_info=True,
            )

    def _collect_room_ids(self) -> list[str]:
        """Collect room names from room config entries.

        Uses raw room_name (e.g. "Living Room") to match Bayesian predictor
        format — the predictor stores room names as-is from room_transitions.
        """
        from ..const import DOMAIN, CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM
        room_ids = []
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                config = {**entry.data, **entry.options}
                if config.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                    room_ids.append(config.get("room_name", entry.title))
        except Exception:
            pass
        return room_ids

    def _get_rooms_energy_total(self) -> float | None:
        """Return sum of energy_today from all room coordinators."""
        from ..const import DOMAIN
        from ..coordinator import UniversalRoomCoordinator
        try:
            rooms_total = 0.0
            for data in self.hass.data.get(DOMAIN, {}).values():
                if isinstance(data, UniversalRoomCoordinator):
                    if hasattr(data, 'data') and isinstance(data.data, dict):
                        energy = data.data.get("energy_today")
                        if energy is not None:
                            rooms_total += energy
            return round(rooms_total, 2) if rooms_total > 0 else None
        except Exception:
            return None

    def _get_occupied_room_count(self) -> int:
        """Return count of occupied rooms from presence coordinator."""
        from ..const import DOMAIN
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return 0
            presence = manager.coordinators.get("presence")
            if presence is None:
                return 0
            count = 0
            for tracker in presence.zone_trackers.values():
                rooms = tracker.to_dict().get("rooms", {})
                for occ in rooms.values():
                    if occ:
                        count += 1
            return count
        except Exception:
            return 0

    def _get_occupancy_counts(self) -> tuple[int, int]:
        """Return (occupied_room_count, occupied_zone_count) from presence coordinator."""
        from ..const import DOMAIN
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return 0, 0
            presence = manager.coordinators.get("presence")
            if presence is None:
                return 0, 0
            room_count = 0
            zone_count = 0
            for tracker in presence.zone_trackers.values():
                zone_occupied = False
                rooms = tracker.to_dict().get("rooms", {})
                for occ in rooms.values():
                    if occ:
                        room_count += 1
                        zone_occupied = True
                if zone_occupied:
                    zone_count += 1
            return room_count, zone_count
        except Exception:
            return 0, 0

    async def _periodic_db_writes(self, decision: dict) -> None:
        """Run periodic DB writes sequentially to avoid SQLite contention."""
        await self._log_energy_history_snapshot(decision)
        await self._log_external_conditions_snapshot()
        await self._save_evse_state()
        await self._save_circuit_state()
        # v3.13.2: Save baselines every 3rd cycle alongside other DB writes
        await self._save_energy_baselines()
        # v3.15.0: Envoy cache + midnight snapshot (serialized with other writes)
        await self._save_envoy_cache()
        await self._save_midnight_snapshot()

    async def _save_circuit_state(self) -> None:
        """Persist SPAN circuit monitor state to DB for restart recovery."""
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        if not self._circuits._circuits:
            return
        try:
            circuits_dict = {}
            for entity_id, circuit in self._circuits._circuits.items():
                circuits_dict[entity_id] = {
                    "was_loaded": circuit.was_loaded,
                    "zero_since": circuit.zero_since,
                    "alerted": circuit.alerted,
                }
            await db.save_circuit_state(circuits_dict)
        except Exception as e:
            _LOGGER.warning("Could not save circuit state to DB: %s", e)

    async def _restore_circuit_state(self) -> None:
        """Restore SPAN circuit monitor state from DB after restart."""
        import time
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            saved = await db.restore_circuit_state()
            if not saved:
                return
            # Ensure circuits are discovered first
            if not self._circuits._discovered:
                self._circuits.discover_circuits()
            now = time.time()
            restored_count = 0
            for entity_id, state in saved.items():
                if entity_id in self._circuits._circuits:
                    circuit = self._circuits._circuits[entity_id]
                    circuit.was_loaded = state.get("was_loaded", False)
                    # H1 fix: Reset stale zero_since to now to avoid
                    # false tripped-breaker alerts from pre-restart timestamps
                    raw_zs = state.get("zero_since")
                    if raw_zs is not None:
                        circuit.zero_since = now
                    else:
                        circuit.zero_since = None
                    circuit.alerted = state.get("alerted", False)
                    restored_count += 1
            if restored_count:
                _LOGGER.info("Restored circuit state for %d circuits", restored_count)
        except Exception as e:
            _LOGGER.warning("Could not restore circuit state: %s", e)

    async def _save_energy_baselines(self) -> None:
        """Persist MetricBaselines (circuit power + peak import) to metric_baselines table."""
        import aiosqlite
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            # Collect all baselines: circuit power + peak import
            all_baselines = list(self._circuits.get_baselines_for_save().values())
            all_baselines.append(self._peak_import_baseline)
            all_baselines.append(self._soc_at_peak_baseline)
            all_baselines.append(self._daily_import_cost_baseline)
            all_baselines.append(self._solar_forecast_error_baseline)
            async with aiosqlite.connect(db.db_file, timeout=30.0) as conn:
                await conn.execute("PRAGMA busy_timeout=30000")
                for baseline in all_baselines:
                    if baseline.sample_count == 0:
                        continue
                    await conn.execute("""
                        INSERT OR REPLACE INTO metric_baselines
                        (coordinator_id, metric_name, scope,
                         mean, variance, sample_count, last_updated)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        baseline.coordinator_id,
                        baseline.metric_name,
                        baseline.scope,
                        baseline.mean,
                        baseline.variance,
                        baseline.sample_count,
                        baseline.last_updated,
                    ))
                saved_count = sum(1 for b in all_baselines if b.sample_count > 0)
                await conn.commit()
                _LOGGER.debug("Saved %d energy baselines", saved_count)
        except Exception as e:
            _LOGGER.warning("Could not save energy baselines: %s", e)

    async def _restore_energy_baselines(self) -> None:
        """Restore MetricBaselines from metric_baselines table."""
        import aiosqlite
        from .coordinator_diagnostics import MetricBaseline
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        # Ensure circuits are discovered so we can match baselines to entity_ids
        if not self._circuits._discovered:
            self._circuits.discover_circuits()
        try:
            async with aiosqlite.connect(db.db_file, timeout=30.0) as conn:
                await conn.execute("PRAGMA busy_timeout=30000")
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute("""
                    SELECT metric_name, scope, mean, variance,
                           sample_count, last_updated
                    FROM metric_baselines
                    WHERE coordinator_id = 'energy'
                """)
                rows = await cursor.fetchall()
                circuit_baselines: dict[str, MetricBaseline] = {}
                unmatched = 0
                stale_unmapped: list[str] = []
                for row in rows:
                    baseline = MetricBaseline(
                        metric_name=row["metric_name"],
                        coordinator_id="energy",
                        scope=row["scope"],
                        mean=row["mean"],
                        variance=row["variance"],
                        sample_count=row["sample_count"],
                        last_updated=row["last_updated"],
                    )
                    if row["metric_name"] == "peak_import_kw":
                        baseline.max_samples = 1500
                        self._peak_import_baseline = baseline
                    elif row["metric_name"] == "soc_at_peak_start":
                        baseline.max_samples = 365
                        self._soc_at_peak_baseline = baseline
                    elif row["metric_name"] == "daily_import_cost":
                        baseline.max_samples = 365
                        self._daily_import_cost_baseline = baseline
                    elif row["metric_name"] == "solar_forecast_error_pct":
                        baseline.max_samples = 365
                        self._solar_forecast_error_baseline = baseline
                    elif row["metric_name"] == "circuit_power":
                        # Scope is friendly_name — reverse-map to entity_id
                        matched = False
                        for eid, circuit in self._circuits._circuits.items():
                            if circuit.friendly_name == row["scope"]:
                                circuit_baselines[eid] = baseline
                                matched = True
                                break
                        if not matched:
                            # v4.7.32 SPAN prune: an unmatched "Unmapped Tab%"
                            # baseline is stale. SPAN's Circuit Name Sync renames a
                            # tab the instant it is assigned a circuit, so a real
                            # circuit is NEVER named "Unmapped Tab N" — an unmatched
                            # one means the tab was since named (the named circuit
                            # relearns under its real name) or the tab is empty.
                            # Delete-and-relearn. Genuinely renamed REAL circuits
                            # (non-"Unmapped Tab") are kept + warned for operator
                            # awareness (no auto-delete of potentially-valuable data).
                            # v4.7.32.1: substring (not startswith) — live scopes are
                            # "Span Left/Right Unmapped Tab N Power" (panel-prefixed),
                            # and older ones are bare "Unmapped Tab N Power". A real
                            # user-named circuit never contains "Unmapped Tab".
                            if "Unmapped Tab" in str(row["scope"]):
                                stale_unmapped.append(row["scope"])
                            else:
                                unmatched += 1
                                _LOGGER.warning(
                                    "Circuit baseline '%s' has no matching circuit "
                                    "(may have been renamed)", row["scope"],
                                )
                if circuit_baselines:
                    self._circuits.restore_baselines(circuit_baselines)
                if stale_unmapped:
                    # Reversible prune: copy each row to a backup table BEFORE
                    # deleting, so a bad prune can be undone with (use OR IGNORE so
                    # a scope that has since relearned is NOT clobbered — Review B1):
                    #   INSERT OR IGNORE INTO metric_baselines
                    #     (coordinator_id,metric_name,scope,mean,variance,
                    #      sample_count,last_updated)
                    #   SELECT coordinator_id,metric_name,scope,mean,variance,
                    #      sample_count,last_updated
                    #   FROM metric_baselines_pruned_backup;
                    from datetime import datetime as _dt, timezone as _tz
                    _pruned_at = _dt.now(_tz.utc).isoformat()
                    await conn.execute(
                        "CREATE TABLE IF NOT EXISTS metric_baselines_pruned_backup ("
                        "coordinator_id TEXT, metric_name TEXT, scope TEXT, "
                        "mean REAL, variance REAL, sample_count INTEGER, "
                        "last_updated TEXT, pruned_at TEXT)"
                    )
                    for _sc in stale_unmapped:
                        await conn.execute(
                            "INSERT INTO metric_baselines_pruned_backup "
                            "SELECT coordinator_id, metric_name, scope, mean, "
                            "variance, sample_count, last_updated, ? "
                            "FROM metric_baselines WHERE coordinator_id='energy' "
                            "AND metric_name='circuit_power' AND scope = ?",
                            (_pruned_at, _sc),
                        )
                        await conn.execute(
                            "DELETE FROM metric_baselines "
                            "WHERE coordinator_id='energy' "
                            "AND metric_name='circuit_power' AND scope = ?",
                            (_sc,),
                        )
                    await conn.commit()
                    _LOGGER.info(
                        "SPAN: pruned %d orphaned 'Unmapped Tab' circuit baselines "
                        "(backed up to metric_baselines_pruned_backup; reversible). "
                        "Affected scopes will relearn under current names.",
                        len(stale_unmapped),
                    )
                if unmatched:
                    _LOGGER.warning(
                        "%d circuit baselines could not be matched", unmatched,
                    )
                _LOGGER.info(
                    "Restored %d energy baselines (peak_import: %d samples)",
                    len(rows) - unmatched - len(stale_unmapped),
                    self._peak_import_baseline.sample_count,
                )
        except Exception as e:
            _LOGGER.debug("Could not restore energy baselines (may not exist yet): %s", e)

    async def async_teardown(self) -> None:
        """Tear down — cancel decision timer first to prevent races, then persist."""
        # Cancel timer FIRST to prevent concurrent _periodic_db_writes
        if self._decision_timer_unsub is not None:
            self._decision_timer_unsub()
            self._decision_timer_unsub = None
        # Save peak import history so it survives restarts
        if self._peak_import_history:
            await self._save_peak_import_history()
        # Save EVSE state for restart recovery
        await self._save_evse_state()
        # v3.13.1: Save circuit monitor state
        await self._save_circuit_state()
        # v3.13.2: Save energy baselines
        await self._save_energy_baselines()
        # v3.15.0: Save envoy cache, midnight snapshot, load shedding level
        await self._save_envoy_cache()
        await self._save_midnight_snapshot()
        await self._save_load_shedding_level()
        # B-M1 / C-C7 fix-up: reset the optimizer-intent unsub handle so
        # re-setup after teardown re-subscribes cleanly (the double-
        # subscribe guard reads ``if self._optimizer_intent_unsub is None``).
        # The actual unsub call happens in ``_cancel_listeners`` because
        # the handle is appended to ``self._unsub_listeners`` at setup.
        self._optimizer_intent_unsub = None
        self._cancel_listeners()
        _LOGGER.info("Energy Coordinator stopped")

    # =========================================================================
    # Public accessors for sensors
    # =========================================================================

    @property
    def tou_engine(self) -> TOURateEngine:
        """Return the TOU rate engine."""
        return self._tou

    @property
    def battery_strategy(self) -> BatteryStrategy:
        """Return the battery strategy."""
        return self._battery

    # v4.2.10: Runtime toggle properties for EC device switches
    @property
    def arbitrage_enabled(self) -> bool:
        """Whether grid arbitrage is active."""
        return self._battery._arbitrage_enabled

    @arbitrage_enabled.setter
    def arbitrage_enabled(self, value: bool) -> None:
        self._battery._arbitrage_enabled = value
        # Pass-2 P2A-MED-1: reset attain latch when the toggle flips.
        # Stale `_attain_state` after a mid-attain disable+re-enable would
        # resume CHARGE with no entry re-evaluation (stale economics).
        self._battery._attain_state = "inactive"
        self._battery._attain_drift_logged = False
        self._battery._attain_charging_ticks = 0
        # Clear the rate-window so the next ENTRY re-seeds cleanly.
        self._battery._attain_soc_history.clear()
        _LOGGER.info("Energy arbitrage: %s", "enabled" if value else "disabled")

    @property
    def ev_tou_enabled(self) -> bool:
        """Whether EV TOU management is active (bidirectional, widened semantics).

        v<next> WS2: this flag now gates BOTH directions of TOU-driven EVSE
        behavior:
        - ON (default): URA pauses the EVSE during peak/mid_peak periods AND
          ensures the EVSE is ON during off_peak (proactive turn-on), unless a
          carry-over guard fires (battery drain / fill-priority / grid-cap /
          arbitrage) or the admin force-charge override is active.
        - OFF: URA disables BOTH directions — no TOU pause during peak, AND
          no proactive turn-on during off_peak. Manual switch control is
          unconstrained by TOU intent.

        Legacy phrasing ("pause/resume") referred to a resume-only off-peak
        branch that only un-paused URA's own pauses; that semantic was
        widened in WS2 to ensure-on (operator decision 1).
        """
        return self._ev_tou_enabled

    @ev_tou_enabled.setter
    def ev_tou_enabled(self, value: bool) -> None:
        self._ev_tou_enabled = value
        _LOGGER.info("EV TOU management: %s", "enabled" if value else "disabled")

    @property
    def dynamic_preset_enabled(self) -> bool:
        """Whether the Dynamic Preset Override Source is active (v4.7.1 Cycle B)."""
        return self._dynamic_preset_enabled

    @dynamic_preset_enabled.setter
    def dynamic_preset_enabled(self, value: bool) -> None:
        self._dynamic_preset_enabled = value
        _LOGGER.info("Dynamic preset overrides: %s", "enabled" if value else "disabled")

    @property
    def offpeak_drain_targets(self) -> dict[str, int]:
        """Current off-peak drain SOC targets by solar quality."""
        return self._battery._drain_targets

    def _check_threshold_ladder(self) -> None:
        """v4.3.0 D3 / v4.5.0 D2: log a WARNING when the ladder is violated.

        v4.5.0: arbitrage_trigger is removed from the gate (forecast-class
        only); validator skips trigger checks when None.
        """
        from .energy_const import validate_threshold_ladder
        warning = validate_threshold_ladder(
            self._battery.reserve_soc,
            self._battery._drain_targets,
            arbitrage_trigger=None,
            peak_buffer_target=self._battery._peak_buffer_target,
        )
        if warning:
            _LOGGER.warning("Threshold ladder violated: %s", warning)

    def set_offpeak_drain(self, quality: str, value: int) -> None:
        """Update a single off-peak drain target at runtime."""
        valid = {"excellent", "good", "moderate", "poor"}
        if quality not in valid:
            _LOGGER.warning("Invalid drain quality '%s' — must be one of %s", quality, valid)
            return
        self._battery._drain_targets[quality] = value
        _LOGGER.info("Off-peak drain %s set to %d%%", quality, value)
        self._check_threshold_ladder()

    @property
    def arbitrage_target(self) -> int:
        """v4.5.0 D2: deprecated alias for peak_buffer_target.

        Kept on the EC API surface for the migration window so any sensor
        automation referring to the old name continues to function. D6 /
        v4.6.0 removes the alias.
        """
        return self._battery._peak_buffer_target

    def set_arbitrage_target(self, value: int) -> None:
        """Update arbitrage SOC charge target at runtime (v4.3.0 D2).

        v4.5.0 D2: alias of set_peak_buffer_target. Kept on the coord for
        the migration window so any sensors/automations referring to the
        old name continue to work.
        """
        self.set_peak_buffer_target(value)

    @property
    def peak_buffer_target(self) -> int:
        """v4.5.0 D2: Current peak buffer target (replaces arbitrage_target)."""
        return self._battery._peak_buffer_target

    def set_peak_buffer_target(self, value: int) -> None:
        """v4.5.0 D2: Update the peak buffer SOC target at runtime."""
        v = int(value)
        self._battery._peak_buffer_target = v
        # Keep alias in sync until callers fully migrate.
        self._battery._arbitrage_target = v
        _LOGGER.info("Peak buffer target set to %d%%", v)
        self._check_threshold_ladder()

    @property
    def arbitrage_charge_lead_time_min(self) -> int:
        """v4.5.0 D2: Current arbitrage charge lead time (minutes)."""
        return self._battery._arbitrage_charge_lead_time_min

    def set_arbitrage_charge_lead_time(self, value: int) -> None:
        """v4.5.0 D2: Update charge lead time at runtime.

        Backstop clamp + WARN log when out of [MIN, MAX]. The number
        entity already enforces these via native_min/max but a
        programmatic caller (or a stale RestoreEntity value) could try
        to write through.
        """
        from .energy_const import (
            MAX_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
            MIN_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
        )
        try:
            v = int(value)
        except (TypeError, ValueError):
            _LOGGER.warning(
                "Arbitrage charge lead time: invalid value %r — ignored", value
            )
            return
        clamped = max(
            MIN_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
            min(MAX_ARBITRAGE_CHARGE_LEAD_TIME_MIN, v),
        )
        if clamped != v:
            _LOGGER.warning(
                "Arbitrage charge lead time %d outside [%d, %d] — clamped to %d",
                v,
                MIN_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
                MAX_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
                clamped,
            )
        self._battery._arbitrage_charge_lead_time_min = clamped
        _LOGGER.info("Arbitrage charge lead time set to %d min", clamped)

    @property
    def ev_battery_drain_soc(self) -> int:
        """Current EV battery-drain pause threshold (v4.3.3)."""
        return self._ev_battery_drain_soc

    def set_ev_battery_drain_soc(self, value: int) -> None:
        """Update EV battery-drain pause threshold at runtime (v4.3.3).

        Slider write goes through here; takes effect on next decision tick.
        Used by determine_battery_drain_actions to gate EV pause.
        """
        self._ev_battery_drain_soc = int(value)
        _LOGGER.info("EV battery drain SOC threshold set to %d%%", int(value))

    @property
    def fill_priority_soc(self) -> int:
        """Current EV fill-priority pause threshold (v4.7.6 D2).

        When SOC < this AND solar forecast remaining >= excess_solar_kwh,
        URA pauses EVSEs/L1 plugs so the home battery fills first.
        """
        return self._fill_priority_soc

    def set_fill_priority_soc(self, value: int) -> None:
        """Update EV fill-priority pause threshold at runtime (v4.7.6 D3.2).

        Slider write goes through here; takes effect on next decision tick.
        """
        self._fill_priority_soc = int(value)
        _LOGGER.info("EV fill-priority SOC threshold set to %d%%", int(value))

    @property
    def excess_solar_soc(self) -> int:
        """Current EV excess-solar turn-ON SOC threshold (v4.7.6.1 D1).

        When home battery SOC >= this AND solar surplus is available, URA
        turns EVSEs/L1 plugs ON even during off-peak pause so the surplus
        is consumed rather than exported.
        """
        return self._excess_solar_soc

    def set_excess_solar_soc(self, value: int) -> None:
        """Update EV excess-solar turn-ON SOC threshold at runtime (v4.7.6.1 D1).

        Slider write goes through here; takes effect on next decision tick
        via the tick-snapshot in _async_evaluate_dynamic_presets (Bug Class
        #14 mitigation — mirrors the v4.7.6 B-M3 fix for fill_priority_soc).
        """
        self._excess_solar_soc = int(value)
        _LOGGER.info("EV excess-solar SOC threshold set to %d%%", int(value))

    async def _check_fill_priority_nm_trip(
        self,
        fill_priority_soc_tick: int | None = None,
    ) -> None:
        """v4.7.6 D4: Fire NM trip once per day on first fill-priority pause.

        Edge detection: tracks previous-tick `_paused_by_fill_priority` empty
        state. Trips LOW NM alert when transitioning empty → non-empty AND the
        trip hasn't fired today.

        Gated by observation mode (Bug Class #23 — gate at dispatch, not in
        handler) because `_send_nm_alert` does not gate observation_mode.

        v4.7.6 fix-up B-M3: `fill_priority_soc_tick` is the tick-snapshot
        captured at the top of `_async_decision_cycle`. Used in the NM
        message body so the threshold reported matches what the rule used
        even if `set_fill_priority_soc` ran mid-tick. Falls back to the
        live attr when omitted (test paths only).
        """
        # v4.7.6 fix-up B-H4: include L1 plug fill-priority set in the
        # currently_paused union so the NM trip fires on L1-only pauses
        # (D4 L1 plug parity). Previously only EVPool's set was checked.
        currently_paused = bool(
            self._ev._paused_by_fill_priority
            or self._smart_plugs._paused_by_fill_priority
        )
        if not currently_paused:
            # Reset edge-detection state when nothing is paused this tick.
            self._fill_priority_was_empty = True
            return

        if not self._fill_priority_was_empty:
            return  # Already paused last tick — no rising edge.

        # v4.7.6 fix-up B-M4: defer the rising-edge consumption until AFTER
        # the observation-mode gate so an observation-mode-suppressed tick
        # doesn't burn the day's edge token silently.
        if self._observation_mode:
            _LOGGER.debug(
                "Fill-priority rising edge in observation mode — NM trip suppressed"
            )
            return

        # Past the obs-mode gate — consume the rising edge.
        self._fill_priority_was_empty = False

        from homeassistant.util import dt as dt_util
        today_iso = dt_util.now().date().isoformat()
        if self._fill_priority_nm_trip_date == today_iso:
            return  # Already tripped today.

        self._fill_priority_nm_trip_date = today_iso
        soc = self._battery.battery_soc
        remaining = self._battery.solcast_remaining
        try:
            # v4.7.6 fix-up B-M3: prefer tick-snapshot threshold for the
            # message body. Falls back to live attr if caller didn't pass.
            target_soc_for_msg = (
                int(fill_priority_soc_tick)
                if fill_priority_soc_tick is not None
                else int(self._fill_priority_soc)
            )
            await self._send_nm_alert(
                title="EVSE Paused for Battery Fill",
                message=(
                    f"EVSE paused for battery fill "
                    f"(SOC {soc:.0f}%, target {target_soc_for_msg}%, "
                    f"solar forecast {remaining:.1f} kWh remaining)"
                    if soc is not None and remaining is not None
                    else "EVSE paused for battery fill (fill-priority active)"
                ),
                severity="low",
                hazard_type="evse_fill_priority",
                location="energy",
            )
            _LOGGER.info(
                "Fill-priority NM trip fired (date=%s, ev_paused=%s, plug_paused=%s)",
                today_iso,
                list(self._ev._paused_by_fill_priority),
                list(self._smart_plugs._paused_by_fill_priority),
            )
        except Exception:
            _LOGGER.warning(
                "Fill-priority NM trip dispatch failed (non-fatal)", exc_info=True
            )

    @property
    def tou_period(self) -> str:
        """Current TOU period."""
        return self._tou.get_current_period()

    @property
    def tou_rate(self) -> float:
        """Current TOU import rate."""
        return self._tou.get_current_rate()

    @property
    def tou_season(self) -> str:
        """Current TOU season."""
        return self._tou.get_season()

    @property
    def battery_status(self) -> dict[str, Any]:
        """Current battery strategy status."""
        return self._battery.get_status()

    @property
    def solar_day_class(self) -> str:
        """Current solar day classification."""
        return self._battery.classify_solar_day()

    @property
    def last_battery_decision(self) -> dict[str, Any]:
        """Last battery decision details."""
        return self._last_battery_decision

    # E2 accessors
    @property
    def pool_optimizer(self) -> PoolOptimizer:
        """Return the pool optimizer."""
        return self._pool

    @property
    def ev_controller(self) -> EVChargerController:
        """Return the EV charger controller."""
        return self._ev

    @property
    def pool_status(self) -> dict[str, Any]:
        """Current pool optimization status."""
        return self._pool.get_status()

    @property
    def ev_status(self) -> dict[str, Any]:
        """Current EV charging status.

        v4.7.6 D4 + D6.3: threads the configured fill-priority target SOC
        and bridges in the SmartPlugController status so L1 plugs appear
        as peer entries with the same 6-key shape as EVSEs.
        """
        try:
            # v4.7.6 fix-up C-H1 / A-L3: thread the configured target SOC
            # into the plug surface so its `pause_reason_human` renders the
            # peer-shaped target string (matches EV format).
            plug_status = self._smart_plugs.get_status(
                fill_priority_target_soc=self._fill_priority_soc,
            )
        except Exception:  # pragma: no cover — defensive
            plug_status = {}
        return self._ev.get_status(
            fill_priority_target_soc=self._fill_priority_soc,
            plug_status=plug_status,
        )

    # E3 accessors
    @property
    def circuit_status(self) -> dict[str, Any]:
        """Current circuit monitor status."""
        return self._circuits.get_status()

    @property
    def generator_status(self) -> dict[str, Any]:
        """Current generator status."""
        return self._generator.get_status()

    # E4 accessors
    @property
    def billing_status(self) -> dict[str, Any]:
        """Current billing status."""
        return self._billing.get_status()

    @property
    def cost_today(self) -> float:
        """Net cost today."""
        return self._billing.cost_today

    @property
    def cost_this_cycle(self) -> float:
        """Net cost so far in billing cycle."""
        return self._billing.cost_this_cycle

    @property
    def predicted_bill(self) -> float | None:
        """Predicted monthly bill."""
        return self._billing.predicted_bill

    @property
    def utility_meter_divergence(self) -> dict[str, Any] | None:
        """Compare utility meter reading against Envoy-derived cycle import.

        Returns dict with divergence info, or None if utility meter not configured.

        Note: The utility meter (SmartHub) resets on its own cycle (typically
        the 1st of the month). URA's billing cycle resets on bill_cycle_day
        (configurable, default 9th). The divergence is only meaningful when
        both cycles started at the same time. The `cycles_aligned` flag
        indicates whether the comparison is valid.
        """
        if not self._utility_meter_entity:
            return None
        state = self.hass.states.get(self._utility_meter_entity)
        if not state or state.state in ("unknown", "unavailable"):
            return None
        try:
            utility_kwh = float(state.state)
        except (ValueError, TypeError):
            return None
        envoy_kwh = self._billing.import_kwh_cycle

        # Check cycle alignment: utility last_reset vs URA cycle start
        cycles_aligned = False
        utility_reset = state.attributes.get("last_reset")
        billing_status = self._billing.get_status()
        ura_cycle_start = billing_status.get("cycle_start_date") if billing_status else None
        if utility_reset and ura_cycle_start:
            # Compare dates (ignore time)
            try:
                from homeassistant.util import dt as dt_util
                u_dt = dt_util.parse_datetime(str(utility_reset))
                u_date = u_dt.date() if u_dt else None
                # ura_cycle_start is typically "YYYY-MM-DD" string
                from datetime import date as _date_cls
                if isinstance(ura_cycle_start, str) and len(ura_cycle_start) >= 10:
                    c_date = _date_cls.fromisoformat(ura_cycle_start[:10])
                else:
                    c_date = None
                if u_date and c_date:
                    cycles_aligned = abs((u_date - c_date).days) <= 2
            except Exception:
                pass

        ref = max(utility_kwh, envoy_kwh, 1.0)
        divergence_pct = abs(utility_kwh - envoy_kwh) / ref * 100
        return {
            "utility_kwh": round(utility_kwh, 2),
            "envoy_kwh": round(envoy_kwh, 2),
            "divergence_pct": round(divergence_pct, 1),
            "cycles_aligned": cycles_aligned,
            "prediction_source": "envoy",
            "utility_entity": self._utility_meter_entity,
        }

    @property
    def current_effective_rate(self) -> float:
        """Current effective import rate."""
        return self._billing.current_effective_rate

    # E5 accessors
    @property
    def forecast_today(self) -> dict[str, Any]:
        """Today's energy forecast."""
        return self._predictor._get_current_prediction()

    @property
    def battery_full_time(self) -> str | None:
        """Estimated time battery reaches 100%.

        Live SOC takes priority, then predictor cache, then hold cache.
        The hold cache retains the last known value through Envoy outages.
        """
        soc = self._battery.battery_soc
        if soc is not None and soc >= 99:
            self._last_battery_full_time = "already_full"
            return "already_full"
        result = self._predictor._battery_full_time
        if result is not None:
            self._last_battery_full_time = result
            return result
        # Envoy offline + predictor stale — return last known value
        return self._last_battery_full_time

    @property
    def forecast_accuracy(self) -> float:
        """Rolling forecast accuracy percentage."""
        return self._accuracy.rolling_accuracy

    @property
    def predicted_import_kwh(self) -> float | None:
        """Predicted net grid exchange today (positive=import, negative=export).

        Simple energy balance: solar powers the house and charges the battery.
        Battery is a buffer — it absorbs surplus solar and covers deficit.

        - Net producer (solar > consumption): battery absorbs up to its
          usable capacity, remainder exports.  Result is negative.
        - Net consumer (solar < consumption): battery covers the deficit
          up to its usable capacity, remainder imports.  Result is positive.
        """
        forecast = self._predictor._get_current_prediction()
        consumption = forecast.get("predicted_consumption_kwh")
        production = forecast.get("predicted_production_kwh")
        if consumption is None or production is None:
            return None

        capacity = self._predictor._get_battery_capacity_kwh()
        reserve = self._battery.reserve_soc
        usable_battery = capacity * (1.0 - reserve / 100.0)

        if production >= consumption:
            # Surplus day — battery absorbs some, rest exports to grid
            surplus = production - consumption
            battery_absorbs = min(usable_battery, surplus)
            return round(-(surplus - battery_absorbs), 1)
        else:
            # Deficit day — battery covers some, rest imports from grid
            deficit = consumption - production
            battery_provides = min(usable_battery, deficit)
            return round(deficit - battery_provides, 1)

    @property
    def predicted_consumption_kwh(self) -> float | None:
        """Predicted total home consumption today (kWh)."""
        return self._predictor._get_current_prediction().get("predicted_consumption_kwh")

    # E6 accessors
    @property
    def energy_situation(self) -> str:
        """Overall energy situation."""
        return self._energy_situation

    @property
    def hvac_constraint(self) -> dict[str, Any]:
        """Current HVAC constraint — full detail for sensors."""
        transition = self._tou.get_next_transition()
        max_runtime = None
        if self._hvac_constraint_mode in ("coast", "shed"):
            max_runtime = int(transition.get("hours_until", 0) * 60)

        soc = self._battery.battery_soc or 0
        solar_class = self._battery.classify_solar_day()

        return {
            "mode": self._hvac_constraint_mode,
            "offset": self._hvac_constraint_offset,
            "max_runtime_minutes": max_runtime,
            "reason": self._hvac_constraint_reason,
            "solar_class": solar_class,
            "soc": soc if soc > 0 else None,
            "forecast_high_temp": self._cached_forecast_high,
            "forecast_low_temp": self._cached_forecast_low,
            "fan_assist": self._hvac_constraint_mode in ("coast", "shed"),
        }

    # boot-decoupling C7 fix: dynamic registration of sub-switches for
    # restore accounting. Each switch (factory and HVACDynamicPresetSwitch)
    # calls this at construction so the pending counter reflects the actual
    # population — no hardcoded 6.
    def register_sub_switch_for_restore_accounting(
        self, unique_suffix: str,
    ) -> None:
        """Register a sub-switch for deferred-restore convergence tracking.

        Idempotent — repeat registrations (e.g. on reload) are no-ops.
        """
        if unique_suffix in self._registered_sub_switches:
            return
        self._registered_sub_switches.add(unique_suffix)
        self._pending_sub_switch_restores += 1
        _LOGGER.debug(
            "EC sub-switch registered for restore accounting: %s "
            "(pending=%d)",
            unique_suffix, self._pending_sub_switch_restores,
        )

    # v4.7.x D2 fix-up H1: sub-switch restore completion tracking
    def notify_sub_switch_restore_complete(self) -> None:
        """Called by each EC sub-switch when its deferred restore completes.

        Decrements the pending-restore counter.  The counter floor is 0 —
        redundant calls (e.g. if a switch fires twice) are safe.
        ECSubSwitchesSyncedSensor calls sub_switches_synced() to read state.
        """
        if self._pending_sub_switch_restores > 0:
            self._pending_sub_switch_restores -= 1
            _LOGGER.debug(
                "EC sub-switch restore complete; %d remaining",
                self._pending_sub_switch_restores,
            )

    def sub_switches_synced(self) -> bool:
        """Return True when all registered EC sub-switches have completed
        their deferred restore.

        Counter population is dynamic (see
        register_sub_switch_for_restore_accounting).
        """
        return self._pending_sub_switch_restores == 0

    @property
    def observation_mode(self) -> bool:
        """Whether observation mode is active (sensors only, no actions)."""
        return self._observation_mode

    @observation_mode.setter
    def observation_mode(self, value: bool) -> None:
        """Set observation mode."""
        self._observation_mode = value
        _LOGGER.info("Energy Coordinator observation mode: %s", value)

    # ------------------------------------------------------------------
    # OC Phase 5 Pillar A — sibling-coordinator handshake
    # ------------------------------------------------------------------

    @callback
    def _on_optimizer_intent(self, intent: dict) -> None:
        """Dispatcher callback for SIGNAL_OPTIMIZER_INTENT.

        Evaluates ``honor_optimizer_intent`` and fires
        ``SIGNAL_OPTIMIZER_INTENT_VETO`` when this coordinator refuses.
        Defensively guards against malformed payloads so the broker can
        never crash a sibling.
        """
        try:
            if not isinstance(intent, dict):
                return
            # B-H1 fix-up: L1 inertness. At shadow/advisory the broker
            # only dispatches intents for observability — no actuation
            # happens, so a veto would be advisory-only AND would inflate
            # the L1 log surface (3 sibling INFO lines + 3 veto dispatches
            # per finding per cycle). Skip both. DEBUG retained so
            # adversarial reviews can still observe the path.
            eff = intent.get("effective_level")
            if eff in ("advisory", "shadow"):
                _LOGGER.debug(
                    "Energy: skipping intent honor at L1 effective_level=%s "
                    "(action_id=%s target=%s)",
                    eff,
                    intent.get("action_id"),
                    intent.get("target_entity"),
                )
                return
            if self.honor_optimizer_intent(intent):
                return
            action_id = intent.get("action_id")
            if not action_id:
                return
            async_dispatcher_send(
                self.hass,
                SIGNAL_OPTIMIZER_INTENT_VETO,
                {
                    "action_id": action_id,
                    "vetoed_by": "energy",
                    "reason": self._last_veto_reason or "energy_policy",
                },
            )
            _LOGGER.info(
                "Optimizer intent vetoed by Energy (action_id=%s reason=%s "
                "target=%s)",
                action_id,
                self._last_veto_reason,
                intent.get("target_entity"),
            )
        except Exception:  # noqa: BLE001 — never crash sibling on broker intent
            _LOGGER.debug(
                "Energy._on_optimizer_intent raised", exc_info=True,
            )

    def honor_optimizer_intent(self, intent: dict) -> bool:
        """Return True to ACK (allow), False to VETO an Optimizer intent.

        Default vetoes (Pillar A safe-defaults from the plan, plus the
        D7(a) coverage broadening from the fix-up pass):
            * ``self._observation_mode`` is True — veto everything.
            * The intent targets an EVSE *surface* (configured switch
              OR span_breaker) AND any of: (a) off-peak charge window
              is active, (b) load-shedding is active. EVSE-surface
              actuation must not race the EV-charging policy or the
              load-shed bookkeeping.
            * The intent targets a smart-plug entity currently under
              active load-shed control (``SmartPlugController._plugs``
              with shed state engaged) — the load-shed controller owns
              that plug while shedding.
            * The intent targets a battery-strategy entity (storage
              mode, reserve SOC, charge-from-grid, grid-enabled).
            * TOU period is unknown OR the lookup raised AND the
              target is an EVSE surface — fail closed (M-5 / A-M1 /
              B-M2). A degraded TOU signal must not silently allow the
              optimizer to actuate the EV plug at the wrong time.

        Read-only — never mutates state (except a rate-limited WARN
        line tracked on the coordinator), never raises. Treats unknown
        payload shapes as "no objection" (return True). The optimizer's
        broker treats no-response as proceed, so an exception inside
        ``honor_optimizer_intent`` cannot wedge the broker.
        """
        # Reset the per-call veto reason so callers reading
        # ``_last_veto_reason`` after a False return see the correct
        # explanation.
        self._last_veto_reason = None

        try:
            target = (intent.get("target_entity") or "").strip()
        except Exception:  # noqa: BLE001
            return True
        if not target:
            return True

        # (a) Blanket observation-mode veto.
        if self._observation_mode:
            self._last_veto_reason = "observation_mode"
            return False

        # (b) EVSE-surface veto — broadened per D7(a). Surface includes
        # the configured ``switch`` AND the ``span_breaker`` so the
        # optimizer can't bypass the EV-charging policy by flipping the
        # breaker. Veto fires during off-peak window OR while load
        # shedding is active (NOT only period=="off_peak").
        try:
            evse_surfaces: set[str] = set()
            for cfg in self._ev._evse.values():
                if not isinstance(cfg, dict):
                    continue
                sw = cfg.get("switch")
                if sw:
                    evse_surfaces.add(sw)
                br = cfg.get("span_breaker")
                if br:
                    evse_surfaces.add(br)
        except Exception:  # noqa: BLE001
            evse_surfaces = set()

        if target in evse_surfaces:
            # M-5 / A-M1 / B-M2 fail-closed: TOU period unknown OR
            # exception → veto. We MUST never actuate an EVSE surface
            # with degraded TOU signal.
            period = None
            tou_degraded = False
            try:
                period = self._tou.get_current_period()
            except Exception:  # noqa: BLE001
                tou_degraded = True
            if period is None:
                tou_degraded = True
            try:
                shed_active = bool(self.load_shedding_active)
            except Exception:  # noqa: BLE001
                shed_active = False
            if tou_degraded:
                self._maybe_warn_degraded("tou_period_unknown")
                self._last_veto_reason = "evse_tou_period_unknown"
                return False
            if period == "off_peak":
                self._last_veto_reason = "evse_offpeak_charge_window"
                return False
            if shed_active:
                self._last_veto_reason = "evse_load_shed_active"
                return False

        # (c) Smart-plug-under-active-load-shed veto — D7(a)(ii).
        # The load-shed controller currently owns any plug it has
        # paused (the optimizer must not flip them back ON), and the
        # plug roster itself (``_plugs``) is the canonical inventory.
        # We veto the entire active set so a controlled plug can't be
        # toggled by the optimizer mid-shed.
        try:
            plugs_under_shed: set[str] = set()
            if bool(self._smart_plugs._paused_by_us):
                plugs_under_shed.update(self._smart_plugs._paused_by_us)
            if bool(self._smart_plugs._paused_by_fill_priority):
                plugs_under_shed.update(
                    self._smart_plugs._paused_by_fill_priority,
                )
            # 4th-pass MEDIUM: drain-protected plugs were omitted — the
            # optimizer could un-pause a battery-drain-paused plug.
            drain_paused = getattr(
                self._smart_plugs, "_paused_by_battery_drain", None,
            )
            if drain_paused:
                plugs_under_shed.update(drain_paused)
        except Exception:  # noqa: BLE001
            plugs_under_shed = set()
        if target in plugs_under_shed:
            self._last_veto_reason = "smart_plug_under_load_shed"
            return False

        # (d) Battery-strategy write veto. The battery strategy machine
        # owns these entities; the optimizer can read them but must not
        # write them at any rung. A-M2 fix-up: resolve fresh from
        # ``entry.options`` per call so a runtime options update is
        # honored without a coordinator restart (no retained snapshot).
        try:
            battery_writeables = self._resolve_battery_writeables_live()
        except Exception:  # noqa: BLE001
            battery_writeables = set()
        if target in battery_writeables:
            self._last_veto_reason = "battery_strategy_write"
            return False

        return True

    def _resolve_battery_writeables_live(self) -> set[str]:
        """A-M2 fix-up: resolve battery-strategy writeable entities from
        live entry options (NOT the cached ``self._entity_config``) so
        operator updates take effect without a coordinator restart.

        Falls back to the cached config if no Coordinator-Manager entry
        is loaded yet (boot path); the fallback preserves the
        pre-fix-up behavior.
        """
        from ..const import (
            CONF_ENTRY_TYPE,
            DOMAIN,
            ENTRY_TYPE_COORDINATOR_MANAGER,
        )
        out: set[str] = set()
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                merged = {**(entry.data or {}), **(entry.options or {})}
                if (
                    merged.get(CONF_ENTRY_TYPE)
                    != ENTRY_TYPE_COORDINATOR_MANAGER
                ):
                    continue
                for key in (
                    CONF_ENERGY_STORAGE_MODE_ENTITY,
                    CONF_ENERGY_RESERVE_SOC_ENTITY,
                    CONF_ENERGY_CHARGE_FROM_GRID_ENTITY,
                    CONF_ENERGY_GRID_ENABLED_ENTITY,
                ):
                    val = merged.get(key)
                    if val:
                        out.add(str(val))
                break
        except Exception:  # noqa: BLE001
            return out
        if not out:
            # Boot fallback — cached config snapshot.
            try:
                for key in (
                    CONF_ENERGY_STORAGE_MODE_ENTITY,
                    CONF_ENERGY_RESERVE_SOC_ENTITY,
                    CONF_ENERGY_CHARGE_FROM_GRID_ENTITY,
                    CONF_ENERGY_GRID_ENABLED_ENTITY,
                ):
                    val = self._entity_config.get(key)
                    if val:
                        out.add(str(val))
            except Exception:  # noqa: BLE001
                pass
        return out

    def _maybe_warn_degraded(self, reason: str) -> None:
        """M-5 rate-limited WARN once when veto inputs degrade.

        Suppresses repeats inside a rolling window (default 5 min) so a
        persistently-degraded TOU signal logs once per window, not once
        per intent.
        """
        try:
            from homeassistant.util import dt as dt_util
            now = dt_util.utcnow()
        except Exception:  # noqa: BLE001
            return
        from datetime import timedelta
        window = timedelta(minutes=5)
        last_map = getattr(self, "_honor_degraded_warn_at", None)
        if not isinstance(last_map, dict):
            last_map = {}
            self._honor_degraded_warn_at = last_map
        last = last_map.get(reason)
        if last is not None and (now - last) < window:
            return
        last_map[reason] = now
        _LOGGER.warning(
            "Energy honor_optimizer_intent: degraded input — %s "
            "(veto fail-closed)",
            reason,
        )

    @property
    def occupancy_weighted(self) -> bool:
        """Whether occupancy-weighted prediction is active."""
        return self._occupancy_weighted

    @occupancy_weighted.setter
    def occupancy_weighted(self, value: bool) -> None:
        """Set occupancy-weighted prediction mode."""
        self._occupancy_weighted = value
        _LOGGER.info("Energy occupancy-weighted prediction: %s", value)

    @property
    def solar_banking_enabled(self) -> bool:
        """Whether HVAC solar banking is enabled (operator master toggle).

        Read by HVACPredictor._is_solar_banking_enabled() to short-circuit the
        solar-banking branch in _check_pre_conditioning when the operator
        flips this OFF from the EC device card.
        """
        return self._solar_banking_enabled

    @solar_banking_enabled.setter
    def solar_banking_enabled(self, value: bool) -> None:
        """Set HVAC solar-banking master enable."""
        self._solar_banking_enabled = bool(value)
        _LOGGER.info("Energy HVAC solar-banking master: %s", value)

    @property
    def delivery_rate(self) -> float:
        """Current delivery + transmission rate per kWh."""
        from .energy_const import PEC_FIXED_CHARGES
        return PEC_FIXED_CHARGES["delivery_per_kwh"] + PEC_FIXED_CHARGES["transmission_per_kwh"]

    # =========================================================================
    # Monitoring accessors (consumption, EV, L1 charger)
    # =========================================================================

    def _get_state_float(self, entity_id: str | None) -> float | None:
        """Get numeric state from entity. None entity_id → None (v4.3.1)."""
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    @property
    def total_consumption_kw(self) -> float | None:
        """Total home consumption from Envoy CT (raw entity value).

        v4.5.0 unit-consistency note: this is mis-named historically — it
        returns the entity's raw state, which may be W or kW depending on
        firmware. Callers that need true kW must read the underlying
        entity's unit_of_measurement and scale, OR use total_consumption_w
        below which always returns W. Renaming this property is deferred
        to v4.6.0 to avoid breaking external sensor automations.
        """
        return self._get_state_float(self._entity_grid_consumption)

    @property
    def total_consumption_w(self) -> float | None:
        """Total home consumption normalized to W.

        v4.5.0 unit-consistency: scales kW → W via unit_of_measurement
        attribute check. Use this for any threshold math.
        """
        eid = self._entity_grid_consumption
        if eid is None:
            return None
        state = self.hass.states.get(eid)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            value = float(state.state)
        except (ValueError, TypeError):
            return None
        uom = state.attributes.get("unit_of_measurement", "")
        if uom in ("kW", "kw"):
            value *= 1000.0
        return value

    @property
    def net_consumption_kw(self) -> float | None:
        """Net consumption (positive=importing, negative=exporting).

        Unit-consistency note: despite the ``_kw`` suffix this returns the
        RAW Envoy entity state, which may be W or kW depending on firmware
        (same historical trap as ``total_consumption_kw``). It is NOT a
        true-kW value. For unit-correct kW use ``net_power_w`` (always W)
        and divide by 1000 at the boundary — which the net-consumption
        display sensor now does. Kept as-is to avoid breaking any external
        reader; do not introduce new callers.
        """
        return self._battery.net_power

    @property
    def evse_garage_a_power(self) -> float | None:
        """EVSE Garage A power draw in watts."""
        from .energy_const import DEFAULT_EVSE_GARAGE_A_POWER_ENTITY
        return self._get_state_float(DEFAULT_EVSE_GARAGE_A_POWER_ENTITY)

    @property
    def evse_garage_b_power(self) -> float | None:
        """EVSE Garage B power draw in watts."""
        from .energy_const import DEFAULT_EVSE_GARAGE_B_POWER_ENTITY
        return self._get_state_float(DEFAULT_EVSE_GARAGE_B_POWER_ENTITY)

    @property
    def l1_charger_active(self) -> bool:
        """Whether any L1 charger socket is on (Moes plug, switch-only)."""
        from .energy_const import DEFAULT_L1_CHARGER_ENTITIES
        for entity_id in DEFAULT_L1_CHARGER_ENTITIES:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state == "on":
                return True
        return False

    @property
    def load_shedding_active(self) -> bool:
        """Whether any load shedding is active (pool reduced, EVs paused, plugs paused)."""
        return (
            self._pool.state != "normal"
            or bool(self._ev._paused_by_us)
            or bool(self._smart_plugs._paused_by_us)
        )

    @property
    def load_shedding_status(self) -> dict[str, Any]:
        """Load shedding status for sensors."""
        active_loads: list[str] = []
        if self._load_shedding_active_level > 0:
            active_loads = LOAD_SHEDDING_PRIORITY[:self._load_shedding_active_level]
        return {
            "enabled": self._load_shedding_enabled,
            "active": self._load_shedding_active_level > 0,
            "level": self._load_shedding_active_level,
            "max_levels": len(LOAD_SHEDDING_PRIORITY),
            "shed_loads": active_loads,
            "threshold_kw": self._get_effective_shedding_threshold(),
            "configured_threshold_kw": self._load_shedding_threshold_kw,
            "learned_threshold_kw": self._learned_threshold_kw,
            "mode": self._load_shedding_mode,
            "sustained_minutes": self._load_shedding_sustained_minutes,
            "sustained_readings": len(self._sustained_import_readings),
        }

    @property
    def battery_decision_status(self) -> dict[str, Any]:
        """Last battery decision for sensors."""
        return self._last_battery_decision

    def get_energy_summary(self) -> dict[str, Any]:
        """Return comprehensive energy state for diagnostics."""
        tou_info = self._tou.get_period_info()
        battery_status = self._battery.get_status()
        return {
            "tou": tou_info,
            "battery": battery_status,
            "pool": self._pool.get_status(),
            # v4.7.6 fix-up C-H1: thread target SOC for consistent rendering.
            "ev": self._ev.get_status(
                fill_priority_target_soc=self._fill_priority_soc,
            ),
            "smart_plugs": self._smart_plugs.get_status(
                fill_priority_target_soc=self._fill_priority_soc,
            ),
            "circuits": self._circuits.get_status(),
            "generator": self._generator.get_status(),
            "billing": self._billing.get_status(),
            "forecast": self._predictor._get_current_prediction(),
            "accuracy": self._accuracy.get_status(),
            "hvac_constraint": self.hvac_constraint,
            "energy_situation": self._energy_situation,
            "load_shedding_active": self.load_shedding_active,
            "decision_interval_minutes": self._decision_interval,
            "tou_transitions_today": self._tou_transition_count,
            "envoy_available": self._battery.envoy_available,
            "envoy_unavailable_count": self._envoy_unavailable_count,
            "envoy_last_available": self._envoy_last_available,
            "observation_mode": self._observation_mode,
            "occupancy_weighted": self._occupancy_weighted,
            "power_profiles": self._power_profiles.get_status(),
            "evse_battery_hold": self._evse_battery_hold_active,
        }

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
try:
    # v5.17.3 D1 — optional import so bootstrap-stubbed test modules that
    # predate the at-boundary listener stay green.
    from homeassistant.helpers.event import async_track_point_in_time
except ImportError:  # pragma: no cover — test-only fallback
    async_track_point_in_time = None  # type: ignore[assignment]

# v5.17.3 review B1 — one-shot WARNING on runtime absence of
# async_track_point_in_time (would indicate a real HA API change,
# not just a test-bootstrap stub). Module-level flag so we log once
# per process regardless of how many arm attempts happen.
_ATP_ABSENCE_WARNED: bool = False

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
    CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY,
    CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
    CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY,
    CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
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
    TOU_BOUNDARY_TICK_DELAY_S,
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


class _DPSkip(Exception):
    """B2c-1 fix-up item 6: sentinel used inside the DP tick try/except to
    short-circuit out of the DP-eval branch when the night-window gate
    (off_peak-only) is closed. Distinct from generic Exception so the
    broad `except Exception` swallow doesn't emit a spurious debug log
    on the (frequent) gate-closed path."""


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
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED,
            CONF_ENERGY_MULTI_DAY_HORIZON_ENABLED,
            CONF_ENERGY_SOLCAST_DAY_3_ENTITY,
            DEFAULT_ARBITRAGE_CHARGE_LEAD_TIME_MIN,
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
        # v5.5.x cycle (c): NO silent finite default for the guard kW.
        # If the operator never set a value, pass None — BatteryStrategy
        # treats `enabled=True but kw=None` as DISABLED (effective inf).
        # Config-flow cross-field validation normally prevents this
        # combination, but the runtime defence covers hand-edited configs.
        _raw_guard_kw = ec.get(CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_KW)
        if _raw_guard_kw is None:
            grid_import_guard_kw = None
        else:
            try:
                grid_import_guard_kw = float(_raw_guard_kw)
            except (TypeError, ValueError):
                grid_import_guard_kw = None
        # Default OFF — mirrors `CONF_ENERGY_GRID_IMPORT_CAP_ENABLED`
        # convention (no DEFAULT_* const). When False, BatteryStrategy
        # collapses the effective threshold to inf so the guard is inert
        # at every consumption site.
        grid_import_guard_enabled = bool(ec.get(
            CONF_ENERGY_ARBITRAGE_GRID_IMPORT_GUARD_ENABLED, False
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
            arbitrage_grid_import_guard_enabled=grid_import_guard_enabled,
            tou_engine=self._tou,  # v4.5.0 D8: charge-window math
            multi_day_horizon_enabled=ec.get(
                CONF_ENERGY_MULTI_DAY_HORIZON_ENABLED, False
            ),
            solcast_day_3_entity=ec.get(CONF_ENERGY_SOLCAST_DAY_3_ENTITY),
        )
        # v5.15.x D1 — Envoy write-verification tripwire. Read-only
        # (invariant W-6). Back-reference on the strategy so
        # get_status() surfaces verifier attrs.
        # v5.20.0 D2 fix-up (D-CRIT-1 + re-pass D-MED-2): install real
        # coordinator backref on the battery strategy so D2's
        # `_fire_d2_nm` can locate `_send_nm_alert`. The class had NO
        # `_coord` / `coordinator` attribute; the initial build getattr'd
        # invented attrs and NM was a production no-op. Installed OUTSIDE
        # the WriteVerifier try-block so an unrelated write-verify import
        # failure cannot silently kill the D2 NM path again. Test wiring:
        # assign `strat._coord = fake_coord` directly.
        self._battery._coord = self
        try:
            from .energy_write_verify import WriteVerifier
            self._write_verifier = WriteVerifier(hass, self)
            self._battery._write_verifier = self._write_verifier
        except Exception:
            _LOGGER.debug("WriteVerifier init failed (swallowed)", exc_info=True)
            self._write_verifier = None
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
        # v5.17.1 fix-up (B-MED-1): edge-detect completion for eager persist
        self._last_arbitrage_chunk_completed: bool = False

        # =================================================================
        # EVSE Drain-Precedence (Session B1) — knob storage + carrier.
        # ---------------------------------------------------------------
        # Entity setters (`set_dp_*` below) push values into these attrs
        # BEFORE `async_update_entry` writeback (matches OffPeakDrainNumber /
        # PeakBufferTargetNumber pattern at number.py:710+). On first boot
        # `ec.get(...)` reads the merged `{**entry.data, **entry.options}`
        # dict — falls back to the module-const defaults from
        # `energy_const.py` (`CONF_DP_*`). Runtime readers wired by
        # Session B2 read these attrs, not the module constants.
        #
        # `_dp_carrier` is the DrainPrecedenceState instance shared with
        # the state machine module + observability sensor + KV persist /
        # restore paths (_save_evse_state / _restore_evse_state below).
        # =================================================================
        from .energy_const import (
            CONF_ENERGY_DP_ENABLE,
            CONF_ENERGY_DP_EVAL_DELAY_MIN,
            CONF_ENERGY_DP_MARGIN_MIN,
            CONF_ENERGY_DP_MUST_START_BY_MIN,
            CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A,
            CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B,
            CONF_ENERGY_DP_HOUSE_LOAD_SOURCE,
            CONF_DP_ENABLE as _DP_ENABLE_DEFAULT,
            CONF_DP_EVAL_DELAY_MIN as _DP_EVAL_DELAY_DEFAULT,
            CONF_DP_MARGIN_MIN as _DP_MARGIN_DEFAULT,
            CONF_DP_MUST_START_BY_MIN_PAST_MIDNIGHT as _DP_MUST_START_BY_DEFAULT,
            CONF_DP_NEEDED_KWH_GARAGE_A as _DP_NEEDED_A_DEFAULT,
            CONF_DP_NEEDED_KWH_GARAGE_B_FALLBACK as _DP_NEEDED_B_DEFAULT,
            CONF_DP_HOUSE_LOAD_SOURCE as _DP_LOAD_SRC_DEFAULT,
            DP_HOUSE_LOAD_SOURCES as _DP_LOAD_SRC_VALID,
        )
        self._dp_enabled: bool = bool(ec.get(
            CONF_ENERGY_DP_ENABLE, _DP_ENABLE_DEFAULT
        ))
        self._dp_eval_delay_min: int = int(ec.get(
            CONF_ENERGY_DP_EVAL_DELAY_MIN, _DP_EVAL_DELAY_DEFAULT
        ))
        self._dp_margin_min: int = int(ec.get(
            CONF_ENERGY_DP_MARGIN_MIN, _DP_MARGIN_DEFAULT
        ))
        self._dp_must_start_by_min: int = int(ec.get(
            CONF_ENERGY_DP_MUST_START_BY_MIN, _DP_MUST_START_BY_DEFAULT
        ))
        self._dp_needed_kwh_garage_a: float = float(ec.get(
            CONF_ENERGY_DP_NEEDED_KWH_GARAGE_A, _DP_NEEDED_A_DEFAULT
        ))
        self._dp_needed_kwh_garage_b: float = float(ec.get(
            CONF_ENERGY_DP_NEEDED_KWH_GARAGE_B, _DP_NEEDED_B_DEFAULT
        ))
        _load_src = ec.get(
            CONF_ENERGY_DP_HOUSE_LOAD_SOURCE, _DP_LOAD_SRC_DEFAULT
        )
        if _load_src not in _DP_LOAD_SRC_VALID:
            _load_src = _DP_LOAD_SRC_DEFAULT
        self._dp_house_load_source: str = str(_load_src)
        # Carrier — Session B2 mutates via try_transition(); observability
        # sensor + KV persist/restore mount this instance directly.
        from .energy_drain_precedence import DrainPrecedenceState
        self._dp_carrier: DrainPrecedenceState = DrainPrecedenceState()
        # Session B2b-i: DP-owned decision-SOC field, distinct from
        # `_evse_hold_soc` (which the EVSE-hold overlay uses). When
        # `_apply_dp_transition` claims a DP pause and requires the reserve
        # floor to include `drain_target`, this field carries the drain
        # target %; the update-in-place leg of `_apply_evse_battery_hold`
        # reads it and folds it into the max()-composition (INV-DP3 fit
        # supremacy). None outside an active DP TRANSITIONED window.
        self._dp_decision_soc: int | None = None

        # v4.0.18: EV grid import cap
        self._grid_import_cap_enabled: bool = ec.get(
            CONF_ENERGY_GRID_IMPORT_CAP_ENABLED, False)
        self._grid_import_cap_kw: float = float(ec.get(
            CONF_ENERGY_GRID_IMPORT_CAP_KW, DEFAULT_GRID_IMPORT_CAP_KW))

        # v4.2.10: EV TOU management toggle (was always-on)
        self._ev_tou_enabled: bool = True

        # Pass-2 P2-HIGH-1 — last-known-good latch for the live
        # charge_from_grid switch read. Survives Envoy blips so the
        # breaker resume guards stay engaged across an `unavailable`/
        # `unknown` window. RAM-only is acceptable: on first boot the
        # default False is correct (no prior grid charge); subsequent
        # ticks update it from clean on/off reads.
        self._last_known_grid_charge_on: bool = False

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
            # H2 (2026-07-13): live battery power (W, +charging/-discharging)
            # sourced from the BatteryStrategy accessor. Callable lets the
            # predictor consult the CURRENT rate at estimate-time rather
            # than a stale snapshot.
            battery_power_w_fn=lambda: (
                self._battery.battery_power_w
                if self._battery is not None else None
            ),
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
        # load-shedding-correctness D4: most-recent shed release reason, for
        # the load_shedding_status sensor surface. One of:
        #   None | "auto" | "respect_manual_off" | "deferred_to_other_owner"
        #   | "respect_manual_speed_change" | "restart_restored"
        self._last_release_reason: str | None = None
        # A/B-HIGH-3 fix-up: cached bundle JSON string for write-on-change
        # throttling in `_periodic_db_writes`. None until first save.
        self._last_load_shed_bundle_str: str | None = None

        self._decision_timer_unsub = None
        # v5.17.3 D1: point-in-time listener for at-boundary TOU tick.
        # A periodic tick at 5min interval lags a TOU transition by up to
        # 5 minutes. This handle fires ONE extra `_async_decision_cycle`
        # at (next_boundary + TOU_BOUNDARY_TICK_DELAY_S) — real wall clock,
        # no synthetic-clock override — so the cycle evaluates the just-
        # started period exactly like a periodic tick would. Then re-arms.
        # Cancelled in `async_teardown`; stored separately from the periodic
        # timer so we don't accidentally double-unsub.
        self._tou_boundary_unsub = None
        # Session B2b-ii: drain-precedence must-start-by fire timer.
        # Set by `_arm_dp_must_start_by_timer` when the state machine
        # enters TRANSITIONED with a live `_dp_carrier.must_start_by_dt`;
        # fires `_on_dp_must_start_by` at the deadline which routes to
        # `_apply_dp_must_start_release` (releases the DP pause + turns
        # EVSEs back on if TOU/grid state allow). Cancellable via
        # `_cancel_dp_must_start_by_timer` on clean reversion or state
        # exit; KV-resurrectable through `restore_from_blob`'s expiry
        # guard (a re-armed timer past the KV `must_start_by_dt` will be
        # rejected by the guard and re-fire on the next decision tick).
        self._dp_must_start_unsub = None
        # Re-entrancy guard: the boundary tick may fire while a periodic
        # tick is already running. Concurrent runs would race the shared
        # `_last_battery_decision` / `_last_reserve_level_desired` stamps.
        # Coordinator has no pre-existing cycle lock; add a cheap async-safe
        # in-flight flag (single-threaded event loop → bool assignment is
        # atomic). See `_async_decision_cycle` docstring.
        self._cycle_in_flight: bool = False

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
        # v5.7.1 — Energy Saver Pre-Cool (EC-owned operator surfaces).
        # Replaces the v4.7-era CONF_HVAC_SOLAR_BANK_ENABLED toggle, which
        # was retired in v5.7.1 (PLANNING_v5.7.x_energy_pre_cool_unification.md
        # D3). The CONF_HVAC_SOLAR_BANK_ENABLED value (if present in
        # options) is migrated to CONF_ENERGY_PRECOOL_ENABLED at
        # async_migrate_entry time — by the time we hit this constructor
        # the new key is authoritative. HVACPredictor reads these via
        # _is_energy_precool_enabled() / _get_energy_precool_offset() /
        # _get_energy_precool_scope() to drive the unified Energy Saver
        # Pre-Cool branch in _check_pre_conditioning.
        from .hvac_const import (
            CONF_ENERGY_PRECOOL_ENABLED,
            DEFAULT_ENERGY_PRECOOL_ENABLED,
            CONF_ENERGY_PRECOOL_OFFSET,
            DEFAULT_ENERGY_PRECOOL_OFFSET,
            CONF_ENERGY_PRECOOL_SCOPE,
            DEFAULT_ENERGY_PRECOOL_SCOPE,
            ENERGY_PRECOOL_SCOPE_VALUES,
        )
        self._energy_precool_enabled: bool = bool(ec.get(
            CONF_ENERGY_PRECOOL_ENABLED, DEFAULT_ENERGY_PRECOOL_ENABLED,
        ))
        self._energy_precool_offset: float = float(ec.get(
            CONF_ENERGY_PRECOOL_OFFSET, DEFAULT_ENERGY_PRECOOL_OFFSET,
        ))
        _raw_scope = ec.get(
            CONF_ENERGY_PRECOOL_SCOPE, DEFAULT_ENERGY_PRECOOL_SCOPE,
        )
        self._energy_precool_scope: str = (
            _raw_scope if _raw_scope in ENERGY_PRECOOL_SCOPE_VALUES
            else DEFAULT_ENERGY_PRECOOL_SCOPE
        )
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
            # v5.15.x — cloud verification oracles (empty → surface's
            # verification is disabled; logged once at INFO by
            # WriteVerifier). Fix-up A-LOW-1: use CONF_* imports.
            CONF_ENERGY_CLOUD_RESERVE_ORACLE_ENTITY: "cloud_reserve_oracle",
            CONF_ENERGY_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY: (
                "cloud_charge_from_grid_oracle"
            ),
            CONF_ENERGY_CLOUD_STORAGE_MODE_ORACLE_ENTITY: (
                "cloud_storage_mode_oracle"
            ),
            CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY: "battery_soc_cloud",
            CONF_ENERGY_SOLCAST_TODAY_ENTITY: "solcast_today",
            CONF_ENERGY_SOLCAST_REMAINING_ENTITY: "solcast_remaining",
            CONF_ENERGY_SOLCAST_TOMORROW_ENTITY: "solcast_tomorrow",
            CONF_ENERGY_WEATHER_ENTITY: "weather",
        }
        result = {}
        for conf_key, strategy_key in key_map.items():
            if conf_key in config:
                result[strategy_key] = config[conf_key]
        # H1 (2026-07-13): cloud oracle DEFAULTS. Cloud-first battery
        # writes are the system's write topology; when the operator has
        # not explicitly wired a cloud oracle in the Cloud Verification
        # section, populate the entity map with the well-known
        # enphase_ev IQ_* entity ids so writes still route to the cloud
        # leg. Tests that only configure the local entity get None and
        # naturally fall back to local (the _cloud_write_target contract).
        from .energy_const import (
            DEFAULT_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
            DEFAULT_CLOUD_RESERVE_ORACLE_ENTITY,
            DEFAULT_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
        )
        result.setdefault(
            "cloud_charge_from_grid_oracle",
            DEFAULT_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY,
        )
        result.setdefault(
            "cloud_reserve_oracle",
            DEFAULT_CLOUD_RESERVE_ORACLE_ENTITY,
        )
        result.setdefault(
            "cloud_storage_mode_oracle",
            DEFAULT_CLOUD_STORAGE_MODE_ORACLE_ENTITY,
        )
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

        # v5.17.3 D1: arm the TOU boundary-aligned point-in-time listener.
        # Must be armed BEFORE the initial evaluation so a boundary that
        # happens to be imminent still fires at wall-clock, not periodic
        # cadence.
        self._arm_tou_boundary_listener()

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

        # v5.14.1 SPAN scope migration re-pass — boot-ordering resilience.
        #
        # Root cause (live-repro 2026-07-11): ``SPANCircuitMonitor
        # .discover_circuits()`` is guarded by ``_discovered`` and runs
        # ONCE inside ``_restore_all_sequential`` during coordinator
        # setup, which typically fires BEFORE the ``span_panel``
        # integration has populated ``hass.states``. When that happens
        # the discovery scan matches zero circuits, ``uid_to_entity`` /
        # ``friendly_to_entity`` are empty, and every friendly-scoped
        # legacy row falls into ``mig_unmatched_left`` and is left in
        # place. The v5.13.1 resumable migration removed the sentinel
        # gate but had nothing to re-run against because the cached
        # discovery result was empty AND never refreshed. Result:
        # friendly-scoped rows persist across every restart.
        #
        # Fix: after ``EVENT_HOMEASSISTANT_STARTED`` (when span_panel is
        # up), force a fresh discovery + re-run the existing (idempotent,
        # transactional) migration path. Guarded by a cheap SQL check so
        # steady-state boots (no unmigrated rows left) do nothing.
        try:
            _ha_running = bool(getattr(self.hass, "is_running", False))
        except Exception:  # noqa: BLE001
            _ha_running = False
        if _ha_running:
            # Reload path — HA is already up. Do the re-pass inline once,
            # cheap-check first so we don't burn a migration for no reason.
            # v5.14.1 review MED-1: track the task so teardown cancels it
            # (Bug Class #50 — untracked task racing a new instance).
            _repass_task = self.hass.async_create_task(
                self._span_scope_migration_repass("reload")
            )
            self._unsub_listeners.append(_repass_task.cancel)
        else:
            try:
                from homeassistant.const import EVENT_HOMEASSISTANT_STARTED  # noqa: PLC0415
            except Exception:  # noqa: BLE001
                EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"

            async def _on_started(_event):
                await self._span_scope_migration_repass("post_started")

            try:
                _unsub_started = self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, _on_started,
                )
                # Bug Class #50: track for teardown.
                self._unsub_listeners.append(_unsub_started)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Energy: failed to register SPAN scope migration "
                    "re-pass listener",
                    exc_info=True,
                )

    async def _span_scope_migration_repass(self, trigger: str) -> None:
        """Post-STARTED SPAN scope migration re-pass (v5.14.1).

        Cheap SQL predicate first: are there any circuit_power rows whose
        scope is NOT already a live unique_id (i.e. still shaped like a
        friendly_name or entity_id)? If none, skip. Otherwise force a
        fresh ``discover_circuits(force=True)`` (span_panel is now up so
        the registry lookup + state scan will resolve the circuits that
        were invisible at setup) and re-run ``_restore_energy_baselines``
        — the migration is per-row idempotent + transactional so the
        already-v2 rows short-circuit and the previously-unmatched
        friendly/entity_id rows finally migrate.
        """
        # v5.14.1 review MED-2 + LOW: at most ONE re-pass per process.
        # Steady-state cost is therefore one COUNT query + one read-only
        # attach scan per boot (no writes — sentinel and rewrites are
        # gated), NOT "a no-op": stated honestly because migrated shapes
        # (span_* uids, extras uids) cannot be reliably distinguished
        # from unmigrated scopes by SQL shape alone.
        if getattr(self, "_span_repass_done", False):
            _LOGGER.debug(
                "SPAN scope migration re-pass (%s): already ran this "
                "process — skip", trigger,
            )
            return
        self._span_repass_done = True
        import aiosqlite
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            # Predicate: any non-v2 circuit_power rows left?
            async with aiosqlite.connect(db.db_file, timeout=10.0) as conn:
                await conn.execute("PRAGMA busy_timeout=10000")
                cursor = await conn.execute(
                    "SELECT COUNT(*) FROM metric_baselines "
                    "WHERE coordinator_id='energy' "
                    "AND metric_name='circuit_power'"
                )
                row = await cursor.fetchone()
                total = int(row[0]) if row else 0
            if total == 0:
                _LOGGER.debug(
                    "SPAN scope migration re-pass (%s): no circuit_power "
                    "rows — skip", trigger,
                )
                return
            # Force fresh discovery so span_panel entities that weren't in
            # hass.states at setup are now picked up.
            try:
                pre = len(self._circuits._circuits)
                new_count = self._circuits.discover_circuits(force=True)
                _LOGGER.info(
                    "SPAN scope migration re-pass (%s): rediscovery "
                    "%d → %d circuits",
                    trigger, pre, new_count,
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "SPAN scope migration re-pass (%s): rediscovery "
                    "failed: %s", trigger, e,
                )
                return
            # Re-run the migration — idempotent + transactional.
            await self._restore_energy_baselines()
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "SPAN scope migration re-pass (%s) failed: %s", trigger, e,
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
                    # Fix 3 (A-MED-2 / C-HIGH-2): re-add UNCONDITIONALLY.
                    # The prior skip-guard left a physically-off device
                    # with no owner and a dead ensure-on (nothing knew to
                    # turn it back on). Under Fix 3 the always-on
                    # `release_all_tou` path (energy.py:~3080) drains the
                    # set AND issues a compensating turn_on on the FIRST
                    # tick when the toggle is OFF, restoring restart-
                    # consistent behavior with in-session toggle-off.
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
                            # Fix 3 (A-MED-2 / C-HIGH-2): re-add
                            # UNCONDITIONALLY; always-on
                            # `release_all_grid_cap` drains + turn_on
                            # next tick when toggle is OFF.
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
                            # Fix 3 (A-MED-2 / C-HIGH-2): re-add
                            # UNCONDITIONALLY; always-on
                            # `release_all_fill_priority` drains + turn_on
                            # next tick when toggle is OFF.
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
            # B2c-3 H-1: Restore DP pause set + reinstall "dp" dispatch
            # owner claim on every restored id so the sticky reversion
            # retry in `_dp_decision_tick` has an owner to release.
            # `restore_from_blob` (energy_drain_precedence.py:323-343,
            # B2c-2) coerces the carrier to HOLD_ONLY on boot even when
            # a future must_start_by_dt was persisted; without a restored
            # `_paused_by_dp`, the HOLD_ONLY orphan retry would find
            # nothing to release → INV-DP2 breach. The 10h staleness
            # gate mirrors the sibling pause-set restores (grid_cap/
            # battery_drain/fill_priority/arbitrage all use the same
            # STALE_MAX_AGE_HOURS bound — defense in depth; the next
            # decision cycle re-evaluates the DP state machine anyway).
            dp_json = await db.restore_energy_state_with_age(
                "evse_dp_paused", max_age_hours=STALE_MAX_AGE_HOURS,
            )
            if dp_json:
                try:
                    for eid in _json.loads(dp_json):
                        if eid in valid_evse_ids:
                            self._ev._paused_by_dp.add(eid)
                            # Reinstall "dp" owner (sibling to fresh
                            # `_apply_dp_transition` claim path at
                            # energy.py:3750). Without this, the sticky
                            # reversion retry would release nothing (owner
                            # set already empty post-restart).
                            self._ev._claim_pause_dispatch_owner(eid, "dp")
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
            # Rider (2026-07-13, B-LOW-2 close): restore write-verification
            # RAM state. Extracted to `_restore_wv_state` for test authority
            # (framing-C C-HIGH-1). Preserves ORIGINAL ISO timestamps
            # (`_last_*_at`, `verified_at`) so age renders honestly and,
            # crucially, so `_check`'s `ledger_at > commanded_at` supersession
            # comparison sees the OLD (restored) ledger_at as strictly less
            # than any FRESH post-boot commanded_at — restored ledger CANNOT
            # false-supersede a fresh check.
            battery = getattr(self, "_battery", None)
            verifier = getattr(self, "_write_verifier", None)
            await self._restore_wv_state(
                db, battery, verifier, STALE_MAX_AGE_HOURS,
            )
            # Session B1 — drain-precedence carrier restore.
            # `restore_from_blob(raw, now_provider=dt_util.now)` enforces
            # INV-DP2 (expired must_start_by → fresh HOLD_ONLY) and the
            # `DP_TRANSITION_MAX_DURATION_H` age gate on TRANSITIONED
            # rows. On any parse error / stale row / missing blob we fall
            # back to a fresh HOLD_ONLY carrier (initialized in __init__).
            try:
                from .energy_drain_precedence import (
                    DP_KV_KEY as _DP_KV_KEY,
                    restore_from_blob as _dp_restore,
                )
                dp_raw = await db.restore_energy_state_with_age(
                    _DP_KV_KEY, max_age_hours=STALE_MAX_AGE_HOURS,
                )
                if dp_raw:
                    self._dp_carrier = _dp_restore(
                        dp_raw, now_provider=dt_util.now,
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "drain-precedence carrier restore failed (swallowed)",
                    exc_info=True,
                )
            if (
                states
                or self._ev._paused_by_grid_cap
                or self._ev._paused_by_battery_drain
                or self._ev._paused_by_fill_priority
                or self._ev._paused_by_arbitrage
                or self._ev._paused_by_dp
                or self._ev._proactive_offpeak_holds
                or self._ev._force_charge_until is not None
            ):
                _LOGGER.info(
                    "Restored EVSE state: paused=%s, excess_solar=%s, "
                    "grid_cap=%s, battery_drain=%s, fill_priority=%s, "
                    "arbitrage=%s, dp=%s, proactive_offpeak_holds=%s, "
                    "force_charge_until=%s",
                    list(self._ev._paused_by_us),
                    list(self._ev._excess_solar_active),
                    list(self._ev._paused_by_grid_cap),
                    list(self._ev._paused_by_battery_drain),
                    list(self._ev._paused_by_fill_priority),
                    list(self._ev._paused_by_arbitrage),
                    list(self._ev._paused_by_dp),
                    list(self._ev._proactive_offpeak_holds),
                    self._ev._force_charge_until.isoformat()
                    if self._ev._force_charge_until else None,
                )
        except Exception as e:
            _LOGGER.warning("Could not restore EVSE state from DB: %s", e)

    async def _restore_wv_state(
        self,
        db,
        battery,
        verifier,
        stale_max_age_hours: float,
    ) -> None:
        """Restore write-verification RAM state from KV (extracted for test
        authority — framing-C C-HIGH-1).

        Byte-identical to the pre-extraction inline block:
          - Preserves ORIGINAL ISO timestamps on the commanded ledger
            (`_last_*_at`) so `_check`'s `ledger_at > commanded_at`
            supersession guard treats restored ledger as strictly older
            than any fresh post-boot commanded_at.
          - Only populates battery ledger fields still `None` (no clobber
            of any command already emitted post-boot).
          - Delegates verifier `_records` rehydration to
            `WriteVerifier.restore_records_from_persist`, which itself
            refuses to clobber a fresh post-boot outcome (NO_DATA guard).
          - Uses the same 10h staleness gate applied to sibling EVSE keys.
        """
        import json as _json
        from homeassistant.util import dt as dt_util
        try:
            ledger_json = await db.restore_energy_state_with_age(
                "wv_commanded_ledger", max_age_hours=stale_max_age_hours,
            )
            if ledger_json and battery is not None:
                payload = _json.loads(ledger_json)

                def _parse(x):
                    if not x:
                        return None
                    try:
                        dt = dt_util.parse_datetime(x)
                        if dt is not None and dt.tzinfo is None:
                            dt = dt.replace(tzinfo=dt_util.UTC)
                        return dt
                    except (ValueError, TypeError):
                        return None

                r = payload.get("reserve_soc") or {}
                if battery._last_reserve_level is None and r.get("commanded") is not None:  # noqa: SLF001
                    battery._last_reserve_level = r.get("commanded")  # noqa: SLF001
                    battery._last_reserve_level_at = _parse(r.get("commanded_at"))  # noqa: SLF001
                c = payload.get("charge_from_grid") or {}
                if battery._last_charge_from_grid_command is None and c.get("commanded") is not None:  # noqa: SLF001
                    battery._last_charge_from_grid_command = c.get("commanded")  # noqa: SLF001
                    battery._last_charge_from_grid_command_at = _parse(c.get("commanded_at"))  # noqa: SLF001
                s = payload.get("storage_mode") or {}
                if battery._last_storage_mode_command is None and s.get("commanded") is not None:  # noqa: SLF001
                    battery._last_storage_mode_command = s.get("commanded")  # noqa: SLF001
                    battery._last_storage_mode_command_at = _parse(s.get("commanded_at"))  # noqa: SLF001
                _LOGGER.info(
                    "Rider: restored write-verification commanded "
                    "ledger from KV (reserve=%s@%s, cfg=%s@%s, "
                    "storage=%s@%s)",
                    battery._last_reserve_level,  # noqa: SLF001
                    battery._last_reserve_level_at,  # noqa: SLF001
                    battery._last_charge_from_grid_command,  # noqa: SLF001
                    battery._last_charge_from_grid_command_at,  # noqa: SLF001
                    battery._last_storage_mode_command,  # noqa: SLF001
                    battery._last_storage_mode_command_at,  # noqa: SLF001
                )
            rec_json = await db.restore_energy_state_with_age(
                "wv_verified_records", max_age_hours=stale_max_age_hours,
            )
            if rec_json and verifier is not None:
                try:
                    verifier.restore_records_from_persist(_json.loads(rec_json))
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "wv verifier restore raised (swallowed)",
                        exc_info=True,
                    )
            # v5.17.1 D2 — restore the arbitrage completed-chunk latch
            # under a boundary-identity staleness check. The plan:
            #   - If persisted boundary datetime has already PASSED
            #     (`boundary_iso <= now`) → DROP the restore. The chunk
            #     it belonged to is over.
            #   - If the current window differs from the persisted one
            #     (e.g. we crossed off_peak entry and `reset_arbitrage_chunk`
            #     already ran, or the schedule changed) → DROP.
            #   - Otherwise repopulate `_arbitrage_chunk_completed=True`
            #     so the first post-boot off_peak tick takes the D1 HOLD
            #     short-circuit rather than draining to the target.
            # Refuses to clobber a FRESH `_arbitrage_chunk_completed=True`
            # already set by a live tick between restart and restore
            # (mirrors wv "restored ≤ fresh" precedence).
            try:
                latch_json = await db.restore_energy_state_with_age(
                    "arbitrage_chunk_latch",
                    max_age_hours=stale_max_age_hours,
                )
                if latch_json and battery is not None:
                    latch_payload = _json.loads(latch_json)
                    completed = bool(latch_payload.get("completed"))
                    boundary_iso = latch_payload.get("boundary_iso")
                    stale = False
                    if not completed:
                        stale = True
                    else:
                        parsed_bnd = (
                            dt_util.parse_datetime(boundary_iso)
                            if boundary_iso else None
                        )
                        if parsed_bnd is None:
                            stale = True
                        else:
                            if parsed_bnd.tzinfo is None:
                                parsed_bnd = parsed_bnd.replace(tzinfo=dt_util.UTC)
                            now_utc = dt_util.utcnow()
                            if parsed_bnd <= now_utc:
                                stale = True
                            else:
                                # Boundary-identity: current live boundary
                                # must match persisted within one hour
                                # (rate table is hour-granular).
                                try:
                                    _live_dt, _, _ = battery._attain_target_boundary(  # noqa: SLF001
                                        dt_util.now(), "off_peak",
                                    )
                                except Exception:  # noqa: BLE001
                                    _live_dt = None
                                if _live_dt is not None:
                                    if _live_dt.tzinfo is None:
                                        _live_dt = _live_dt.replace(
                                            tzinfo=dt_util.UTC,
                                        )
                                    delta = abs(
                                        (parsed_bnd - _live_dt).total_seconds()
                                    )
                                    if delta > 3600:
                                        stale = True
                    if stale:
                        _LOGGER.info(
                            "Rider: arbitrage chunk latch NOT restored "
                            "(stale/passed boundary=%s completed=%s)",
                            boundary_iso, completed,
                        )
                    elif battery._arbitrage_chunk_completed:  # noqa: SLF001
                        _LOGGER.debug(
                            "Rider: arbitrage chunk latch — fresh live "
                            "value already set; skipping restore clobber",
                        )
                    else:
                        battery._arbitrage_chunk_completed = True  # noqa: SLF001
                        battery._arbitrage_active = True  # noqa: SLF001
                        _LOGGER.info(
                            "Rider: restored arbitrage chunk latch "
                            "(completed=True boundary=%s) — first "
                            "off_peak tick will HOLD at target",
                            boundary_iso,
                        )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "arbitrage chunk latch restore raised (swallowed)",
                    exc_info=True,
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "wv persist restore failed (swallowed)", exc_info=True,
            )

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
            # B2c-3 H-1: DP pause set. Sibling to grid_cap/battery_drain/
            # fill_priority/arbitrage — every other pause owner survives
            # restart; DP was the outlier. Without this KV, a restart
            # mid-TRANSITIONED left the EVSE physically OFF with no
            # owner and no reversion driver (INV-DP2 breach). Restored
            # in `_restore_evse_state`; the HOLD_ONLY orphan retry in
            # `_dp_decision_tick` then dispatches turn_on once TOU +
            # peers permit.
            await db.save_energy_state(
                "evse_dp_paused",
                _json.dumps(list(self._ev._paused_by_dp)),
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
            # Rider (2026-07-13, B-LOW-2 close): persist write-verification
            # RAM state so a restart does not blind the reversion sweep +
            # `last_verified_write_*` attrs until the next command. Reuses
            # this existing 15-min save cadence + teardown hook — no new
            # timer (Bug Class #19/#42). Two KV keys:
            #   `wv_commanded_ledger` — the three `_last_*_command(_at)`
            #      tuples on `energy_battery` (source-of-truth for
            #      supersession + reversion sweep).
            #   `wv_verified_records` — WriteVerifier `_records` per
            #      surface (backs `last_verified_write_*` display attrs).
            # Timestamps go out as tz-aware ISO (Bug Class #21). Restore
            # side PRESERVES them so age renders honestly.
            try:
                battery = getattr(self, "_battery", None)
                if battery is not None:
                    ledger_payload: dict[str, dict[str, Any]] = {}

                    def _iso(x):
                        if x is None:
                            return None
                        try:
                            return x.isoformat()
                        except Exception:  # noqa: BLE001
                            return None

                    ledger_payload["reserve_soc"] = {
                        "commanded": battery._last_reserve_level,  # noqa: SLF001
                        "commanded_at": _iso(battery._last_reserve_level_at),  # noqa: SLF001
                    }
                    ledger_payload["charge_from_grid"] = {
                        "commanded": battery._last_charge_from_grid_command,  # noqa: SLF001
                        "commanded_at": _iso(
                            battery._last_charge_from_grid_command_at,  # noqa: SLF001
                        ),
                    }
                    ledger_payload["storage_mode"] = {
                        "commanded": battery._last_storage_mode_command,  # noqa: SLF001
                        "commanded_at": _iso(
                            battery._last_storage_mode_command_at,  # noqa: SLF001
                        ),
                    }
                    await db.save_energy_state(
                        "wv_commanded_ledger",
                        _json.dumps(ledger_payload),
                    )
                verifier = getattr(self, "_write_verifier", None)
                if verifier is not None:
                    records_payload = verifier.dump_records_for_persist()
                    await db.save_energy_state(
                        "wv_verified_records",
                        _json.dumps(records_payload),
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "wv persist save failed (swallowed)", exc_info=True,
                )
            # v5.17.1 D2 — persist arbitrage completed-chunk latch + the
            # window identity (boundary_dt) so a restart mid-hold does
            # NOT re-trigger the 2026-07-14 incident (rung_0 closes gate
            # on reboot, drain fallback releases the buffer). Payload:
            #   {"completed": bool, "boundary_iso": "<tz-aware ISO>"}
            # Restore side drops the latch when the persisted boundary
            # has passed (staleness = boundary-identity mismatch), so a
            # `reset_arbitrage_chunk` firing before restore cannot be
            # undone. Follows the existing rider conventions:
            # no new timer, tz-aware ISO (Bug Class #21), 10h age gate
            # via `restore_energy_state_with_age`.
            try:
                from homeassistant.util import dt as dt_util
                battery = getattr(self, "_battery", None)
                if battery is not None:
                    boundary_iso: str | None = None
                    if getattr(battery, "_arbitrage_chunk_completed", False):
                        try:
                            _bnd_dt, _, _mins = battery._attain_target_boundary(  # noqa: SLF001
                                dt_util.now(), "off_peak",
                            )
                            if _bnd_dt is not None:
                                if _bnd_dt.tzinfo is None:
                                    _bnd_dt = _bnd_dt.replace(tzinfo=dt_util.UTC)
                                boundary_iso = _bnd_dt.isoformat()
                        except Exception:  # noqa: BLE001
                            boundary_iso = None
                    latch_payload = {
                        "completed": bool(
                            getattr(battery, "_arbitrage_chunk_completed", False)
                        ),
                        "boundary_iso": boundary_iso,
                    }
                    await db.save_energy_state(
                        "arbitrage_chunk_latch",
                        _json.dumps(latch_payload),
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "arbitrage chunk latch persist save failed (swallowed)",
                    exc_info=True,
                )
            # Session B1 — drain-precedence carrier persist.
            # Mirrors the arbitrage-latch pattern above: single JSON blob
            # under `DP_KV_KEY` in `energy_state`. Restore side is
            # `_restore_evse_state` → `restore_from_blob`, which enforces
            # INV-DP2 must-start-by expiry and the
            # `DP_TRANSITION_MAX_DURATION_H` age gate on the persisted
            # transitioned state. `serialize_for_kv` returns a compact JSON
            # string. Best-effort — swallow to match sibling latches.
            try:
                from .energy_drain_precedence import (
                    DP_KV_KEY as _DP_KV_KEY,
                    serialize_for_kv as _dp_serialize,
                )
                carrier = getattr(self, "_dp_carrier", None)
                if carrier is not None:
                    await db.save_energy_state(
                        _DP_KV_KEY,
                        _dp_serialize(carrier),
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "drain-precedence carrier persist save failed (swallowed)",
                    exc_info=True,
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
        """Restore load shedding active level + bundle from DB on startup.

        load-shedding-correctness D2:
          * Prefers atomic `load_shedding_bundle` JSON (level + pre-shed
            pool speed + EV pause set + plug pause set) and re-populates
            in-memory ownership state.
          * Falls back to the legacy integer-only `load_shedding_level`
            key for back-compat.
          * Does NOT re-issue `switch.turn_off` / `number.set_value`
            actions: LIVE STATE IS AUTHORITY post-restart (mirrors
            v5.3.7/v5.3.9 reboot recovery). The next escalation tick
            catches up if reality drifted.

        Sets a grace period to prevent immediate de-escalation before
        sustained readings buffer refills.
        """
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        import json
        bundle_str: str | None = None
        try:
            bundle_str = await db.restore_energy_state("load_shedding_bundle")
        except Exception as e:  # noqa: BLE001 — defensive
            _LOGGER.debug("Could not restore load shedding bundle: %s", e)
            bundle_str = None

        restored_from_bundle = False
        if bundle_str:
            try:
                bundle = json.loads(bundle_str)
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Load shedding bundle parse failed (%s) — "
                    "falling back to legacy integer restore",
                    e,
                )
                bundle = None
            if isinstance(bundle, dict):
                try:
                    level = int(bundle.get("level", 0))
                    self._load_shedding_active_level = level
                    pool_orig = bundle.get("pool_original_speed")
                    if pool_orig is not None:
                        try:
                            self._pool._original_speed = float(pool_orig)
                            # B-CRIT-2 fix-up: the pool's OTHER owner
                            # (TOU PoolOptimizer.determine_actions) gates
                            # restore on ``_state != POOL_STATE_NORMAL``.
                            # Without setting REDUCED on restore the pool
                            # is orphaned at POOL_REDUCED_SPEED until a
                            # fresh in-peak de-escalation happens to fire.
                            from .energy_pool import POOL_STATE_REDUCED
                            self._pool._state = POOL_STATE_REDUCED
                        except (ValueError, TypeError):
                            self._pool._original_speed = None
                    ev_set = bundle.get("ev_set") or []
                    plug_set = bundle.get("plug_set") or []
                    if isinstance(ev_set, list):
                        self._ev._paused_by_load_shed = {
                            str(x) for x in ev_set
                        }
                    if isinstance(plug_set, list):
                        self._smart_plugs._paused_by_load_shed = {
                            str(x) for x in plug_set
                        }
                    # C-HIGH-1 fix-up: rehydrate per-device "was on at
                    # shed-time" so post-restart release honors manual-OFF.
                    ev_was_on = bundle.get("ev_was_on_at_shed") or {}
                    plug_was_on = bundle.get("plug_was_on_at_shed") or {}
                    if isinstance(ev_was_on, dict):
                        self._ev._load_shed_was_on_at_shed = {
                            str(k): bool(v) for k, v in ev_was_on.items()
                        }
                    if isinstance(plug_was_on, dict):
                        self._smart_plugs._load_shed_was_on_at_shed = {
                            str(k): bool(v) for k, v in plug_was_on.items()
                        }
                    if level > 0:
                        self._load_shedding_grace_cycles = 3
                        self._last_release_reason = "restart_restored"
                        _LOGGER.info(
                            "Restored load shedding bundle: level=%d "
                            "ev=%d plugs=%d pool_orig=%s",
                            level,
                            len(self._ev._paused_by_load_shed),
                            len(self._smart_plugs._paused_by_load_shed),
                            self._pool._original_speed,
                        )
                    restored_from_bundle = True
                except (ValueError, TypeError) as e:
                    _LOGGER.warning(
                        "Load shedding bundle field invalid (%s) — "
                        "falling back to legacy restore",
                        e,
                    )

        if not restored_from_bundle:
            # Legacy integer-only restore (older deploy).
            try:
                level_str = await db.restore_energy_state("load_shedding_level")
                if level_str is not None:
                    self._load_shedding_active_level = int(level_str)
                    if self._load_shedding_active_level > 0:
                        self._load_shedding_grace_cycles = 3
                        _LOGGER.info(
                            "Restored load shedding level (legacy): %d "
                            "(grace period: %d cycles)",
                            self._load_shedding_active_level,
                            self._load_shedding_grace_cycles,
                        )
            except (ValueError, TypeError):
                pass
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("Could not restore load shedding level: %s", e)

    async def _save_load_shedding_level(self) -> None:
        """Persist load shedding state to DB.

        load-shedding-correctness D2: writes a SINGLE atomic JSON bundle
        (`load_shedding_bundle`) — one KV row covers level + pool pre-
        shed speed + EV/plug pause sets. The atomic bundle (rather than
        split keys) mirrors the v5.2.2 batched-write lesson: one write
        per cycle, not N. Keeps the legacy `load_shedding_level` key for
        a back-out window.
        """
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        import json
        bundle = {
            "level": int(self._load_shedding_active_level),
            "pool_original_speed": (
                float(self._pool._original_speed)
                if self._pool._original_speed is not None
                else None
            ),
            "ev_set": sorted(self._ev._paused_by_load_shed),
            "plug_set": sorted(self._smart_plugs._paused_by_load_shed),
            # C-HIGH-1 fix-up: persist per-device live-state-at-shed so
            # restart-then-release honors manual-OFF (the device was off
            # when claimed → it stays off on release).
            "ev_was_on_at_shed": dict(self._ev._load_shed_was_on_at_shed),
            "plug_was_on_at_shed": dict(
                self._smart_plugs._load_shed_was_on_at_shed
            ),
        }
        try:
            bundle_str = json.dumps(bundle, sort_keys=True)
        except (TypeError, ValueError) as e:
            _LOGGER.warning("Could not serialize load shedding bundle: %s", e)
            return
        # A/B-HIGH-3 fix-up: throttle on-change for periodic-write callers.
        # If the bundle bytes match the last persisted bundle, skip the DB
        # round-trip (cheap, but mirrors the v5.2.2 write-flood lesson —
        # don't spin the queue unnecessarily).
        if bundle_str == getattr(self, "_last_load_shed_bundle_str", None):
            return
        try:
            await db.save_energy_state("load_shedding_bundle", bundle_str)
            # Legacy back-out key — one cycle of dual-write.
            await db.save_energy_state(
                "load_shedding_level", str(self._load_shedding_active_level)
            )
            self._last_load_shed_bundle_str = bundle_str
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Could not save load shedding bundle: %s", e)

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

            # R1 (2026-07-16): stash source marker for the DAO write below.
            predicted_source: str | None = None

            if actual_kwh is not None:
                self._predictor.record_actual_consumption(actual_kwh)

                # Evaluate yesterday's forecast accuracy
                forecast = self._predictor._get_current_prediction()
                predicted_consumption = forecast.get("predicted_consumption_kwh")
                predicted_source = forecast.get("predicted_consumption_source")
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
                        predicted_consumption_source=predicted_source,
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
        predicted_consumption_source: str | None = None,
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
                predicted_consumption_source=predicted_consumption_source,
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

    def _dp_needed_kwh_plugged(self) -> float:
        """Sum needed_kwh only over currently-plugged-in EVSEs.

        B2c-2 fix-up (item 1 — MEDIUM): the pre-fix `needed_kwh` summed
        BOTH per-EVSE knobs unconditionally, so a ~100 kWh worst-case
        total made the transition's `fits before must-start-by` check
        nearly never true when only one car was plugged in.

        Membership predicate mirrors the transition-entry scan at
        `_dp_decision_tick` (charging=True) plus the DP-owned paused set
        (`_paused_by_dp`), so a car that has just been paused by an
        earlier tick still contributes its needed_kwh until the state
        machine leaves TRANSITIONED. Cars not plugged in contribute 0.

        B2c-3 M-1 (accepted gap): a plugged car that is idle under car-
        side scheduling (not drawing power AND not DP-paused) contributes
        0 kWh here and can auto-start mid-window. `_get_evse_state`
        (energy_pool.py:293) exposes only `is_on`, `power`, `status`,
        `charging`, `power_source` — none of which is a reliable
        plugged/connected signal across the EVSE integrations we
        support (Emporia W, Tesla Wall Connector, Wallbox; the `status`
        attribute string is manufacturer-specific and not verified).
        Widening the predicate on an invented / unverified attribute
        would risk `_dp_get_state`-style shape drift; INV-DP2 liveness
        (must_start_by fire) is the accepted backstop for this shape,
        forcing the car ON at the deadline regardless of the missed
        contribution here.
        """
        # Fixed keying today: two named knobs matching the well-known
        # EVSE ids in DEFAULT_EVSE_ENTITIES (energy_pool.py:163-176).
        _per_id = {
            "garage_a": float(getattr(self, "_dp_needed_kwh_garage_a", 0.0)),
            "garage_b": float(getattr(self, "_dp_needed_kwh_garage_b", 0.0)),
        }
        total = 0.0
        for evse_id in self._ev._evse:  # noqa: SLF001
            need = _per_id.get(evse_id)
            if not need:
                continue
            try:
                plugged = (
                    evse_id in self._ev._paused_by_dp  # noqa: SLF001
                    or self._ev._get_evse_state(evse_id).get(  # noqa: SLF001
                        "charging", False,
                    )
                )
            except Exception:  # noqa: BLE001
                plugged = False
            if plugged:
                total += need
        return total

    def _dp_house_load_kw(self, ev_load_w: float | None) -> float:
        """Resolve live house-load (kW) for the drain-precedence tick.

        B2c-1 fix-up (item 2 — CRITICAL, was 0.0 stub).

        Two independent readings, honoring
        `CONF_DP_HOUSE_LOAD_SOURCE` selector values:
            * "live_span" — SPAN mains (r1 + r2) in W, minus EVSE draw.
            * "r1_base"   — R1 fitted-model daily prediction / 24h.
            * "max_span_r1" (default) — max of the two.

        Both readings are None-safe (missing / stale entity returns None).
        If BOTH are unavailable, returns 0.0 — the caller feeds this into
        `TransitionInputs.house_load_kw`, and `_dp_maybe_tick` treats a
        non-positive value as MISSING_INPUTS → abstain (no state change).
        """
        # (a) Live SPAN mains — sum r1 + r2 (W), subtract EVSE draw.
        span_r1 = self._get_state_float("sensor.span_panel_current_power")
        span_r2 = self._get_state_float("sensor.span_panel_current_power_2")
        live_kw: float | None = None
        if span_r1 is not None or span_r2 is not None:
            total_w = (span_r1 or 0.0) + (span_r2 or 0.0)
            total_w -= float(ev_load_w or 0.0)
            live_kw = max(0.0, total_w / 1000.0)

        # (b) R1 fitted-model base: predicted daily consumption / 24h.
        base_kw: float | None = None
        try:
            forecast = self._predictor._get_current_prediction()  # noqa: SLF001
            pc = forecast.get("predicted_consumption_kwh")
            if pc is not None:
                base_kw = float(pc) / 24.0
        except Exception:  # noqa: BLE001
            base_kw = None

        src = getattr(self, "_dp_house_load_source", "max_span_r1")
        if src == "live_span":
            return float(live_kw) if live_kw is not None else 0.0
        if src == "r1_base":
            return float(base_kw) if base_kw is not None else 0.0
        # "max_span_r1" default
        candidates = [v for v in (live_kw, base_kw) if v is not None]
        return float(max(candidates)) if candidates else 0.0

    def _dp_decision_tick(
        self, decision: dict[str, Any], period: str, ev_load_w: float | None,
    ) -> None:
        """Drain-precedence per-cycle tick body (B2c-1 fix-up extraction).

        Moved out of `_decision_cycle_impl` so tests can drive the exact
        block bytes end-to-end. Callers wrap this in `try/except _DPSkip`
        (night-gate short-circuit) + generic `except Exception` (defensive
        swallow).

        Fix-up items landed here:
            1. CRITICAL — paused-aware exit predicate (was `not
               _is_any_evse_charging` → flapped false the same tick DP
               dispatched turn_off).
            2. CRITICAL — live `house_load_kw` (was 0.0 stub).
            3. HIGH     — real fully-blind signal (was invented attr).
            4. HIGH     — second plug-in re-scan (car B claimed +1 tick).
            5. HIGH     — kill-switch hoist BEFORE night gate (mid-window
               flip-off releases pause + reverts carrier same-tick,
               daytime or not).
            6. HIGH     — night-window gate (off_peak only) via
               `_tou.get_current_period()` — never hardcode hours.
        """
        from homeassistant.util import dt as dt_util  # local for tests
        from .energy_drain_precedence import (
            is_dp_enabled as _dp_is_enabled,
            _dp_maybe_tick as _dp_tick,
            TransitionInputs as _DPInputs,
            compute_must_start_by as _dp_compute_must_start_by,
            DPState as _DPState,
        )

        # ---- item 5: kill-switch hoist (runs unconditionally FIRST) ----
        _dp_on = _dp_is_enabled(self)
        if not _dp_on:
            _has_dp_state = (
                bool(self._ev._paused_by_dp)  # noqa: SLF001
                or self._dp_decision_soc is not None
                or self._dp_carrier.state != _DPState.HOLD_ONLY
            )
            if _has_dp_state:
                self._apply_dp_reversion(tou_period=period)
                _unsub = getattr(self, "_dp_must_start_unsub", None)
                if _unsub is not None:
                    try:
                        _unsub()
                    except Exception:  # noqa: BLE001
                        pass
                    self._dp_must_start_unsub = None
                self._dp_carrier.state = _DPState.HOLD_ONLY
                self.hass.async_create_task(self._save_evse_state())

        # ---- B2c-3 H-2: sticky retry driver (HOLD_ONLY orphan) ----
        # After H-2 made `_apply_dp_reversion` sticky on peer/TOU
        # deferral, we need a driver that re-fires reversion each cycle
        # until the set drains. The kill-switch hoist above covers the
        # switch-OFF path; this covers switch-ON restart-orphan cleanup
        # (H-1 restore path leaves a non-empty `_paused_by_dp` with a
        # HOLD_ONLY carrier from `restore_from_blob`'s coercion) AND
        # the normal TRANSITIONED→HOLD_ONLY retry when the initial
        # reversion deferred. Runs BEFORE the night-window gate: the
        # TOU-defer inside reversion will keep sticky during peak,
        # and off_peak returns will drain cleanly. Gate on `_dp_on`
        # so a disabled switch doesn't compete with the hoist above
        # (the hoist already handled it via _has_dp_state).
        if (
            _dp_on
            and self._dp_carrier.state == _DPState.HOLD_ONLY
            and self._ev._paused_by_dp  # noqa: SLF001
        ):
            self._apply_dp_reversion(tou_period=period)

        # ---- item 6: night-window gate ----
        if not _dp_on or self._tou.get_current_period() != "off_peak":
            raise _DPSkip()

        _prev_dp_state = self._dp_carrier.state
        _now_dp = dt_util.now()
        _soc = decision.get("soc")

        # ---- item 3: real fully-blind signal ----
        try:
            _env_ok = bool(self._battery.envoy_available)
        except Exception:  # noqa: BLE001
            _env_ok = True
        try:
            _bat_soc = self._battery.battery_soc
        except Exception:  # noqa: BLE001
            _bat_soc = None

        _dp_inputs = _DPInputs(
            dp_enabled=True,
            is_blind_hold=bool((not _env_ok) and _bat_soc is None),
            force_charge_active=(
                self._ev._force_charge_until is not None  # noqa: SLF001
                and self._ev._force_charge_until > _now_dp  # noqa: SLF001
            ),
            soc=int(_soc) if _soc is not None else None,
            drain_target_soc=int(self._ev_battery_drain_soc),
            any_evse_charging=self._is_any_evse_charging(),
            charger_rate_kw=float((ev_load_w or 0.0) / 1000.0),
            # B2c-2 item 1: per-plugged-car sum. Cars not plugged in do
            # not contribute their worst-case need to the fits check.
            needed_kwh=self._dp_needed_kwh_plugged(),
            # ---- item 2: live house-load ----
            house_load_kw=self._dp_house_load_kw(ev_load_w),
            now=_now_dp,
            must_start_by_dt=_dp_compute_must_start_by(
                _now_dp,
                minutes_past_midnight=self._dp_must_start_by_min,
            ),
            margin_min=int(self._dp_margin_min),
            eval_delay_min=int(self._dp_eval_delay_min),
        )

        def _persist_dp(_c):
            self.hass.async_create_task(self._save_evse_state())

        _dp_tick(
            self._dp_carrier, _dp_inputs,
            now_provider=dt_util.now,
            persister=_persist_dp,
        )

        # Fresh entry to TRANSITIONED: actuate + arm must-start-by timer.
        if (
            _prev_dp_state != _DPState.TRANSITIONED
            and self._dp_carrier.state == _DPState.TRANSITIONED
        ):
            _pause_ids = [
                eid for eid in self._ev._evse  # noqa: SLF001
                if self._ev._get_evse_state(eid).get("charging", False)  # noqa: SLF001
            ]

            class _DPAct:
                transition = True
                drain_target_soc = int(self._ev_battery_drain_soc)
                evse_ids_to_pause = _pause_ids
            self._apply_dp_transition(_DPAct())
            if self._dp_carrier.must_start_by_dt is not None:
                self._arm_dp_must_start_by_timer(
                    self._dp_carrier.must_start_by_dt,
                )

        # ---- item 4: second-plug-in re-scan while TRANSITIONED ----
        if self._dp_carrier.state == _DPState.TRANSITIONED:
            _fresh = [
                eid for eid in self._ev._evse  # noqa: SLF001
                if self._ev._get_evse_state(eid).get("charging", False)  # noqa: SLF001
                and eid not in self._ev._paused_by_dp  # noqa: SLF001
            ]
            if _fresh:
                class _DPActRescan:
                    transition = True
                    drain_target_soc = int(self._ev_battery_drain_soc)
                    evse_ids_to_pause = _fresh
                self._apply_dp_transition(_DPActRescan())

        # State-machine-driven revert edge (future-proof; primary paths
        # are the paused-aware exit below + must-start-by fire callback).
        if (
            _prev_dp_state == _DPState.TRANSITIONED
            and self._dp_carrier.state == _DPState.HOLD_ONLY
        ):
            self._apply_dp_reversion(tou_period=period)

        # ---- item 1: paused-aware exit predicate ----
        _revert = False
        if self._dp_carrier.state == _DPState.TRANSITIONED:
            _drain = int(self._ev_battery_drain_soc)
            if _soc is not None and int(_soc) <= _drain:
                _revert = True
        if self._dp_carrier.state == _DPState.MUST_START_FORCED:
            _revert = True
        if (
            self._dp_carrier.state == _DPState.TRANSITIONED
            and not self._ev._paused_by_dp  # noqa: SLF001
            and not self._is_any_evse_charging()
        ):
            _revert = True
        if _revert and self._dp_carrier.state == _DPState.TRANSITIONED:
            from .energy_drain_precedence import try_transition as _dp_try
            _dp_try(
                self._dp_carrier, _DPState.HOLD_ONLY,
                now_provider=dt_util.now,
            )
            self._apply_dp_reversion(tou_period=period)
            self.hass.async_create_task(self._save_evse_state())

    def _apply_evse_battery_hold(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Override battery reserve to captured SOC when EVSEs are charging.

        Uses the SOC captured at hold start to prevent ratchet-down effect
        where each cycle locks to progressively lower SOC.

        ------------------------------------------------------------------
        RESERVE COMPOSITION — single authoritative reference
        ------------------------------------------------------------------
        The reserve % emitted through the reserve action is the max() over
        every contributor below. All units are % SOC (0-100); each sign is
        a FLOOR (minimum acceptable reserve). max() preserves the strongest
        protection; no contributor may demote another.

        Contributors, in precedence order (matches Session B2b-iii
        `WriteVerifier._resolve_hold_owner` at
        energy_write_verify.py:1389-1418 and the effective-desired
        composition at :1418-1451):

          1. Strategy base + folds (`decision["actions"][*].data.value`,
             AKA `existing_val` in the update-in-place leg). Composed on
             the strategy side before this overlay runs:
               * reserve_soc knob                (energy_battery.py:4407)
               * inclement partial_hold clamp    (energy_battery.py:4451-4453)
               * inclement full_hold             (energy_battery.py:4428)
               * arbitrage / attain floor        (energy_battery.py:4439,4447)
             All folded into `reserve_floor` and emitted by
             `_result` (energy_battery.py:3562-3564).
          2. EVSE hold overlay (`hold_reserve` — captured at hold entry,
             stored in `self._evse_hold_soc`; set/cleared by the
             hold-active caller in `_result` energy.py:3546 + evaluate
             path energy.py:4498-4505). Clamped UP to
             `_last_reserve_level_desired` (or ledger fallback on boot
             HOLD-CURRENT paths) in the append leg to avoid oscillation
             under strategy holds (energy.py:3290-3309, v5.17.1 D-HIGH-2
             / v5.17.3 D-MED-1).
          3. DP-owned drain floor (`_dp_decision_soc` — energy.py:370;
             stamped by `_apply_dp_transition` :3444 when the DP state
             machine enters TRANSITIONED, cleared by `_apply_dp_reversion`
             :3515 / `_apply_dp_must_start_release` :3565). Folded into
             BOTH branches:
               * update-in-place leg   (energy.py:3224-3231, INV-DP3)
               * append leg            (energy.py:3320-3325, INV-DP3 parity)
             INV-DP3 is monotonic max() supremacy — the fit-supremacy
             invariant guarantees the transition floor cannot be demoted
             for the duration of TRANSITIONED.
          4. Stand-down gate (D2-HIGH-1). Applied AFTER the max()
             composition on the post-fold effective value. If a hard
             stand-down is pinned on that value for the reserve surface
             (`WriteVerifier.is_standdown_active_for_value` at
             energy_write_verify.py:1417-1436), the overlay emits NO
             reserve action for this tick — mirrors `_result`'s
             stand-down skip so the overlay side cannot re-break a
             pinned surface. Any change in effective desire cancels the
             gate (pinned value no longer matches) and dispatch resumes.
             Update-in-place leg: energy.py:3241-3251. Append leg:
             energy.py:3331-3337.
          5. Deadband suppression (`_result` responsibility, not this
             overlay's). `_result` deadband (energy_battery.py :3834+
             — INV-D2-DEADBAND / INV-EV-DEADBAND) suppresses dispatch
             within ±2%; the ledger-stamp at :3268-3270 / :3357-3359
             keeps the commanded ledger in sync with the effective
             post-max() value so the write-verification sweep does not
             false-alarm `write_reverted` during standing holds.

        Downstream, the write-verifier's `_effective_reserve_desired`
        (energy_write_verify.py :1418-1451) recomposes the same contributor
        set on the READ side so the pending watchdog + reversion sweep
        treat DP-elevated / hold-elevated / inclement-elevated reserves as
        the desired value, not as wedges. Any new floor added to this
        method MUST also be added to `_effective_reserve_desired` — the
        two composers must stay in lock-step (INV-DP5 mirror invariant).
        ------------------------------------------------------------------
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
        # H1 (2026-07-13): the reserve action target is emitted by
        # `_result` via role="write" (cloud-first). Match on the same leg
        # so the update-in-place branch actually finds the existing
        # action; append-new-action branch also emits to the same leg.
        reserve_entity = self._battery._get_entity(
            "reserve_soc_number", DEFAULT_RESERVE_SOC_ENTITY,
            role="write",
        )

        # v5.19.0 fix-up 2 (Review D re-pass, D2-HIGH-1) — stand-down gate.
        # `_result` guards its normal dispatch leg via
        # `WriteVerifier.is_standdown_active_for_value` (energy_battery.py
        # :4519-4536). The overlay re-emits the reserve unconditionally
        # in BOTH branches (update-in-place + append), bypassing that
        # gate — a hard stand-down pinned on `hold_reserve` would then be
        # re-broken every tick from the overlay side. Read the verifier
        # None-safe (boot/tests may have wv=None) and, when the gate is
        # active on the exact hold value, emit NO reserve action from the
        # overlay for this tick. Semantics per operator directive: if the
        # effective desire or hold_reserve changes vs the pinned value,
        # the gate flips False → dispatch resumes.
        _wv_overlay = getattr(self, "_write_verifier", None)

        def _standdown_pinned_on(value: int) -> bool:
            """None-safe check: True iff hard stand-down is pinned on
            `value` for the reserve surface. Boot/tests may have
            verifier=None → returns False (gate off).
            """
            if _wv_overlay is None:
                return False
            try:
                from .energy_write_verify import (  # noqa: PLC0415
                    WRITE_VERIFY_SURFACE_RESERVE,
                )
                return bool(_wv_overlay.is_standdown_active_for_value(
                    WRITE_VERIFY_SURFACE_RESERVE, int(value),
                ))
            except Exception:  # noqa: BLE001
                return False

        # Update existing reserve action or add new one. The EVSE hold may
        # only RAISE the reserve floor, never lower it: an existing reserve
        # action already carries the floor that the battery strategy decided
        # (e.g. an inclement partial_hold/full_hold floor, or the normal
        # reserve_soc). Capturing an EVSE-hold SOC below that floor must not
        # undercut it — max() preserves whichever protection is stronger.
        for i, action in enumerate(decision["actions"]):
            if action.get("target", "") == reserve_entity:
                existing_val = action.get("data", {}).get("value", hold_reserve)
                # Session B2b-i INV-DP3 (fit-supremacy) composition — the
                # update-in-place leg is the single reserve-write site that
                # every strategy floor already flows through:
                #   - `existing_val` carries the BatteryStrategy-composed
                #     inclement_partial_hold + arbitrage/attain floor
                #     (energy_battery.py:4407,4428,4439,4447 all write via
                #     `decision.reserve_floor`; `reserve_floor` itself is
                #     the max of reserve_soc + inclement partial_hold clamp
                #     at energy_battery.py:4451-4453).
                #   - `hold_reserve` is the EVSE-hold captured SOC
                #     (energy.py:299 `_evse_hold_soc`, appended by the
                #     hold-active caller in `_result` at energy.py:3546).
                #   - `_dp_decision_soc` is the DP-owned drain-target %
                #     stamped by `_apply_dp_transition` (energy.py init
                #     ~line 363) when the drain-precedence state machine
                #     enters TRANSITIONED and requires the reserve floor to
                #     include the drain target (INV-DP3 — the composition
                #     must be monotonic max(), never demote).
                # Each contributor is a % SOC (0-100); sign = floor
                # (minimum reserve level). max() preserves the strongest
                # protection across all four sources.
                _dp_soc = getattr(self, "_dp_decision_soc", None)
                try:
                    if _dp_soc is not None:
                        effective = max(
                            int(existing_val),
                            int(hold_reserve),
                            int(_dp_soc),
                        )
                    else:
                        effective = max(int(existing_val), int(hold_reserve))
                except (TypeError, ValueError):
                    effective = hold_reserve
                # D2-HIGH-1 gate: if stand-down is pinned on the
                # effective value being emitted, drop the reserve action
                # from this overlay tick (mirrors `_result` stand-down
                # skip). If effective differs from the pinned value,
                # the gate returns False → normal resume.
                if _standdown_pinned_on(int(effective)):
                    _LOGGER.debug(
                        "EVSE overlay: reserve action SKIPPED "
                        "(stand-down active for value=%d)",
                        int(hold_reserve),
                    )
                    decision["actions"] = [
                        a for j, a in enumerate(decision["actions"])
                        if j != i
                    ]
                    return decision
                decision["actions"][i] = {**action, "data": {"value": effective}}
                # D2 (INV-D2-LEDGER): stamp the hold-elevated reserve
                # into the commanded ledger. `_result` (energy_battery.py
                # :3562-3564) already stamped the pre-overlay strategy
                # desired; overwrite with the effective post-max() value
                # so the write-verification sweep does NOT false-alarm
                # `write_reverted` during standing holds with deadband
                # suppressing dispatch (cloud sees `effective`, ledger
                # must too). Only stamp when the overlay actually raised
                # the emitted value (byte-identical on no-op path per
                # INV-D2-DEADBAND / INV-EV-DEADBAND).
                # reserve_level unit = % SOC (0-100), sign = floor.
                try:
                    if int(effective) != int(existing_val):
                        from homeassistant.util import dt as dt_util
                        _new = int(max(0, min(100, int(effective))))
                        if self._battery._last_reserve_level != _new:  # noqa: SLF001
                            self._battery._last_reserve_level_at = dt_util.utcnow()  # noqa: SLF001
                        self._battery._last_reserve_level = _new  # noqa: SLF001
                except (TypeError, ValueError, AttributeError):
                    pass
                return decision

        # No reserve action yet — add one using configured entity.
        # v5.17.1 fix-up (D-HIGH-2): the append path used the raw
        # `_evse_hold_soc` captured once at hold entry. Under a standing
        # strategy hold (e.g. arbitrage completed-chunk HOLD at 80) with
        # the `_result` 2% deadband suppressing the strategy's own reserve
        # action, this overlay could append `set_value(hold_soc)` — for
        # example 45 — while hardware carried 80, producing 80↔45
        # oscillation. Mirror the update-in-place `max()` semantics:
        # clamp `hold_reserve` UP to the strategy-desired reserve for this
        # tick (`_last_reserve_level_desired`, which `_result` populates
        # BEFORE the deadband decision — see energy_battery.py :3834).
        # Never lowers the EVSE hold; only raises it to preserve the
        # standing strategy protection. Also covered by the inclement-
        # floor path via the strategy floor pre-baked into desired.
        # reserve_level unit = % SOC (0-100), sign = floor (minimum).
        try:
            _desired = getattr(
                self._battery, "_last_reserve_level_desired", None,
            )
            # v5.17.3 D3 (Tier-3 D-MED-1): on boot HOLD-CURRENT paths
            # (BatteryStrategy hold-current bypass), `_last_reserve_level_desired`
            # is None because `_result` is bypassed. Without a fallback,
            # this append could set a sub-hold reserve (e.g. 45) while
            # hardware carries a strategy-restored 80 → oscillation. Fall
            # back to the commanded ledger `_last_reserve_level`, which
            # `_restore_wv_state` restores from KV at boot (energy.py:1381)
            # so the ledger IS populated even before `_result` fires.
            _ledger = getattr(
                self._battery, "_last_reserve_level", None,
            )
            _clamp_ref = _desired if _desired is not None else _ledger
            if _clamp_ref is not None:
                hold_reserve = max(int(hold_reserve), int(_clamp_ref))
        except (TypeError, ValueError, AttributeError):
            pass
        # Session B2b-ii INV-DP3 (append-leg composition parity). The
        # update-in-place leg above folds `_dp_decision_soc` into its
        # max()-composition; the no-prior-reserve-action branch must do
        # the SAME so a cycle with no strategy reserve action still emits
        # the composed DP floor. Each contributor is a % SOC (0-100),
        # sign = floor (minimum reserve level). max() preserves the
        # strongest protection. Emitted through the standard reserve
        # action leg → v5.19.0 stand-down gate (re-checked below on the
        # post-fold value) and INV-DP5 `_last_reserve_level` stamp ride
        # this path unchanged.
        _dp_soc_append = getattr(self, "_dp_decision_soc", None)
        try:
            if _dp_soc_append is not None:
                hold_reserve = max(int(hold_reserve), int(_dp_soc_append))
        except (TypeError, ValueError):
            pass
        # D2-HIGH-1 gate: skip append when stand-down pinned on the
        # POST-clamp emitted value. Ledger stamp below is likewise
        # skipped so we don't advance `_last_reserve_level_at` on a
        # no-emit tick. Re-check against the post-clamp `hold_reserve`
        # (may have been raised by the desired-clamp above).
        if _standdown_pinned_on(int(hold_reserve)):
            _LOGGER.debug(
                "EVSE overlay: reserve append SKIPPED "
                "(stand-down active for value=%d)",
                int(hold_reserve),
            )
            return decision
        decision["actions"].append({
            "service": "number.set_value",
            "target": reserve_entity,
            "data": {"value": hold_reserve},
        })
        # D2 (INV-D2-LEDGER): stamp the hold-elevated reserve into the
        # commanded ledger so `current_park_floor()` sees the value the
        # hardware will actually see, not the pre-overlay strategy desired.
        # Without this, the write-verification sweep can raise a false
        # `write_reverted` when the deadband suppresses dispatch (see
        # PLANNING_energy_pause_release_hygiene.md D2). Only fires on the
        # append path — the update-in-place branch above uses `return`
        # before this point but also stamps via the dispatch tap when the
        # action actually flushes; here we cover the "no prior reserve
        # action + hold raised floor" case.
        # reserve_level unit = % SOC (0-100), sign = floor (minimum).
        try:
            from homeassistant.util import dt as dt_util
            _new = int(max(0, min(100, int(hold_reserve))))
            if self._battery._last_reserve_level != _new:  # noqa: SLF001
                self._battery._last_reserve_level_at = dt_util.utcnow()  # noqa: SLF001
            self._battery._last_reserve_level = _new  # noqa: SLF001
        except (TypeError, ValueError, AttributeError):
            pass
        return decision

    def _apply_dp_transition(self, decision: Any) -> None:
        """EVSE drain-precedence actuation entry-point (Session B2b-i).

        Called by B2b-ii from the decision-cycle wiring when the DP state
        machine enters TRANSITIONED with a fitting eval and requires an
        EVSE pause + composed reserve floor write. This method does NOT
        run the state machine itself (`_dp_maybe_tick` in
        energy_drain_precedence.py owns that); it performs the SIDE
        EFFECTS the state edge implies:
            1. Claim any currently-charging EVSE into
               `EVChargerController._paused_by_dp` and dispatch
               `switch.turn_off` (via the existing `_claim_pause_dispatch_owner`
               reference-counted owner "dp") — mirrors the v5.3.9
               arbitrage-pause pattern.
            2. Stamp `_dp_decision_soc` with the drain target %; the
               update-in-place leg of `_apply_evse_battery_hold` folds
               this into the max()-composition on the NEXT decision cycle
               (INV-DP3 — never demote a floor). The write itself flows
               through `_apply_evse_battery_hold` on the standard reserve
               action leg, so v5.19.0 stand-down gate + INV-DP5
               `_desired_stamped_at` / `_last_reserve_level` stamps ride
               that path unchanged (byte-identical no-op on non-DP ticks).

        Not yet wired into the decision cycle — B2b-ii adds the call site.
        Tests invoke this method directly with a synthetic decision
        carrying `drain_target_soc` + the list of EVSE ids to pause.

        `decision`: TransitionDecision from `evaluate_dp_transition` plus
        the outer coordinator's extension attributes. Duck-typed here
        because B2b-ii will settle the exact shape. Required attrs:
            - `transition` (bool) — must be True to actuate
            - `drain_target_soc` (int %) — value stamped into `_dp_decision_soc`
            - `evse_ids_to_pause` (Iterable[str]) — pause targets
        """
        try:
            if not getattr(decision, "transition", False):
                return
            drain_soc = int(getattr(decision, "drain_target_soc", 0) or 0)
            evse_ids = list(getattr(decision, "evse_ids_to_pause", []) or [])
        except (TypeError, ValueError):
            _LOGGER.warning(
                "drain-precedence: _apply_dp_transition rejected malformed "
                "decision %r", decision,
            )
            return

        # (1) Pause the EVSEs into `_paused_by_dp` + claim dispatch owner
        # "dp". `_ev` is the EVChargerController (energy.py:276).
        for evse_id in evse_ids:
            self._ev._paused_by_dp.add(evse_id)  # noqa: SLF001
            self._ev._claim_pause_dispatch_owner(evse_id, "dp")  # noqa: SLF001
            switch_entity = (
                self._ev._evse.get(evse_id, {}).get("switch", "")  # noqa: SLF001
            )
            if not switch_entity:
                continue
            state = self._ev._get_evse_state(evse_id)  # noqa: SLF001
            if state.get("is_on"):
                # Best-effort dispatch — B2b-ii will decide whether this
                # rides the coordinator's action queue instead. For the
                # slice we honor the pause via direct service call so
                # tests can observe the intent side-effect.
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        "switch", "turn_off",
                        {"entity_id": switch_entity},
                        blocking=False,
                    )
                )
                _LOGGER.info(
                    "drain-precedence: paused EVSE %s (target=%d%%)",
                    evse_id, drain_soc,
                )

        # (2) Stamp the DP-owned decision SOC. INV-DP3 fit supremacy: the
        # next `_apply_evse_battery_hold` tick folds this into the
        # existing max() so the reserve floor cannot demote below
        # drain_target for the duration of the TRANSITIONED window.
        # Cleared by B2b-ii's reversion path when the state machine exits
        # TRANSITIONED.
        self._dp_decision_soc = drain_soc

    # ------------------------------------------------------------------
    # Session B2b-ii — reversion + must-start-by fire
    # ------------------------------------------------------------------

    def _apply_dp_reversion(self, tou_period: str | None = None) -> None:
        """Clean reversion of the DP TRANSITIONED window.

        Called by the decision-cycle wiring when `_dp_maybe_tick` drives
        the carrier from TRANSITIONED → HOLD_ONLY (charge complete OR
        floor released OR kill switch flipped). Symmetric with
        arbitrage-release in energy_pool.py:1507-1556 (see v5.15.0
        sticky release-at-floor F machinery — mirrored here):

            - STICKY deferral: on peer-owner conflict OR non-off_peak
              TOU, KEEP `_paused_by_dp` membership AND the "dp" dispatch
              claim so a later decision tick can retry. Only on
              successful dispatch (or EVSE already on) do we discard
              the id + drop the "dp" owner.
            - `_dp_decision_soc` is cleared only when the pause set is
              fully drained. INV-DP3 max()-composition thus keeps the
              floor pinned for any deferred member; when the last id
              releases, the floor collapses cleanly.
            - Cancel the must-start-by timer regardless (state machine
              has already exited TRANSITIONED — the deadline is moot).

        B2c-3 fix-up (H-2): the pre-fix loop discarded membership + drop
        the "dp" owner BEFORE the peer/TOU check, so a deferred member
        was stranded with no owner and no retry driver (kill-switch flip
        during mid_peak → car off through peak). Sticky mirrors the
        v5.15.0 pattern; retry driver lives in `_dp_decision_tick` (the
        kill-switch hoist + a new HOLD_ONLY orphan-cleanup call), keyed
        off `_has_dp_state` / `_paused_by_dp` truthiness — both of
        which stay armed while any sticky member remains.
        """
        # Cancel the must-start-by timer first so a race between clean
        # reversion and the deadline can't fire release twice.
        self._cancel_dp_must_start_by_timer()
        for evse_id in list(self._ev._paused_by_dp):  # noqa: SLF001
            # H-2 STICKY: check defer conditions BEFORE mutating
            # membership/owner. Peer-owner OR non-off_peak TOU defer
            # keeps the DP claim so the next tick retries.
            if (
                evse_id in self._ev._paused_by_arbitrage  # noqa: SLF001
                or evse_id in self._ev._paused_by_battery_drain  # noqa: SLF001
                or evse_id in self._ev._paused_by_fill_priority  # noqa: SLF001
                or evse_id in self._ev._paused_by_grid_cap  # noqa: SLF001
                or evse_id in self._ev._paused_by_load_shed  # noqa: SLF001
                or evse_id in self._ev._paused_by_us  # noqa: SLF001
            ):
                _LOGGER.info(
                    "drain-precedence release: %s — peer owner still holds, "
                    "keeping DP claim (sticky)",
                    evse_id,
                )
                continue
            if tou_period is not None and tou_period != "off_peak":
                _LOGGER.info(
                    "drain-precedence release: %s — TOU=%s, keeping DP claim "
                    "(sticky)",
                    evse_id, tou_period,
                )
                continue
            switch_entity = (
                self._ev._evse.get(evse_id, {}).get("switch", "")  # noqa: SLF001
            )
            if not switch_entity:
                # No switch configured — drop the claim; nothing to
                # dispatch and no retry can help.
                self._ev._paused_by_dp.discard(evse_id)  # noqa: SLF001
                self._ev._release_pause_dispatch_owner(evse_id, "dp")  # noqa: SLF001
                continue
            state = self._ev._get_evse_state(evse_id)  # noqa: SLF001
            # About to release cleanly (dispatch turn_on OR already on).
            self._ev._paused_by_dp.discard(evse_id)  # noqa: SLF001
            self._ev._release_pause_dispatch_owner(evse_id, "dp")  # noqa: SLF001
            if not state.get("is_on"):
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        "switch", "turn_on",
                        {"entity_id": switch_entity},
                        blocking=False,
                    )
                )
                _LOGGER.info(
                    "drain-precedence: resumed EVSE %s (clean reversion)",
                    evse_id,
                )
        # H-2: only collapse the composed floor when the set is fully
        # drained. A deferred sticky member must continue to pin the
        # DP floor into `_apply_evse_battery_hold`'s max() (INV-DP3).
        if not self._ev._paused_by_dp:  # noqa: SLF001
            self._dp_decision_soc = None

    def _apply_dp_must_start_release(self, tou_period: str | None = None) -> None:
        """Must-start-by fire (INV-DP2 car-charge liveness).

        Called when the state machine reaches MUST_START_FORCED
        (deadline hit while still TRANSITIONED). Behavior is the same
        SHAPE as `_apply_dp_reversion` — release the DP pause + turn
        EVSEs back on — but the RATIONALE is different (must-start-by
        overrides drain-target arithmetic). We still honor STRONGER
        owner claims (a live grid-cap / load-shed / fill-priority hold
        outranks DP even at must-start-by; those owners are safety /
        cost holds that shouldn't be blown through by DP-liveness), but
        we do NOT defer on TOU period: INV-DP2 states the car MUST
        start by the deadline regardless of TOU.
        """
        self._cancel_dp_must_start_by_timer()
        for evse_id in list(self._ev._paused_by_dp):  # noqa: SLF001
            # H-2 STICKY parity: safety/cost peer defer keeps the DP
            # claim so a later tick can retry the forced ON once the
            # peer clears. INV-DP2 liveness still trumps TOU here — we
            # do NOT gate on TOU period.
            if (
                evse_id in self._ev._paused_by_grid_cap  # noqa: SLF001
                or evse_id in self._ev._paused_by_load_shed  # noqa: SLF001
                or evse_id in self._ev._paused_by_fill_priority  # noqa: SLF001
            ):
                _LOGGER.info(
                    "drain-precedence must-start-by fire: %s — safety/cost "
                    "owner holds, keeping DP claim (sticky)",
                    evse_id,
                )
                continue
            switch_entity = (
                self._ev._evse.get(evse_id, {}).get("switch", "")  # noqa: SLF001
            )
            if not switch_entity:
                # No switch — drop claim; nothing dispatch can do.
                self._ev._paused_by_dp.discard(evse_id)  # noqa: SLF001
                self._ev._release_pause_dispatch_owner(evse_id, "dp")  # noqa: SLF001
                continue
            state = self._ev._get_evse_state(evse_id)  # noqa: SLF001
            self._ev._paused_by_dp.discard(evse_id)  # noqa: SLF001
            self._ev._release_pause_dispatch_owner(evse_id, "dp")  # noqa: SLF001
            if not state.get("is_on"):
                self.hass.async_create_task(
                    self.hass.services.async_call(
                        "switch", "turn_on",
                        {"entity_id": switch_entity},
                        blocking=False,
                    )
                )
                _LOGGER.info(
                    "drain-precedence must-start-by fire: forced EVSE %s ON "
                    "(deadline reached)",
                    evse_id,
                )
        # Sticky-safe floor collapse (INV-DP3 parity with reversion).
        if not self._ev._paused_by_dp:  # noqa: SLF001
            self._dp_decision_soc = None

    def _cancel_dp_must_start_by_timer(self) -> None:
        """Idempotent cancel of the must-start-by point-in-time listener."""
        unsub = getattr(self, "_dp_must_start_unsub", None)
        if unsub is not None:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "drain-precedence must-start-by unsub raised (swallowed)",
                    exc_info=True,
                )
            self._dp_must_start_unsub = None

    def _arm_dp_must_start_by_timer(self, fire_at) -> None:
        """Arm the must-start-by point-in-time fire (INV-DP2 liveness).

        Chained pattern lifted from `_arm_tou_boundary_listener`:
            - idempotent re-arm (cancel any prior handle first),
            - swallow `async_track_point_in_time` absence in test bootstraps,
            - skip fires already-in-past (KV-restore path may restore a
              deadline that's already elapsed → handled by the eval on the
              next tick),
            - callback `_on_dp_must_start_by` runs `_apply_dp_must_start_release`
              and does NOT re-arm (fires once per TRANSITIONED window;
              cleaned up by reversion or must-start-fire itself).

        KV-resurrection: `restore_from_blob` (energy_drain_precedence.py:
        333) already rejects expired deadlines on boot, so a stored
        `must_start_by_dt` that's still in the future can be handed to
        this arm helper straight from the restored carrier.
        """
        if async_track_point_in_time is None:
            return
        self._cancel_dp_must_start_by_timer()
        try:
            from homeassistant.util import dt as dt_util
            now_local = dt_util.now()
            if fire_at <= now_local:
                _LOGGER.debug(
                    "drain-precedence must-start-by fire %s already in the past "
                    "(now=%s) — not arming; next decision tick will handle",
                    fire_at, now_local,
                )
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            self._dp_must_start_unsub = async_track_point_in_time(
                self.hass, self._on_dp_must_start_by, fire_at,
            )
            _LOGGER.info(
                "drain-precedence: must-start-by fire armed at %s",
                fire_at.isoformat() if hasattr(fire_at, "isoformat") else fire_at,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "drain-precedence: async_track_point_in_time failed for %s "
                "— must-start-by fire not armed (decision cycle backstop)",
                fire_at, exc_info=True,
            )
            self._dp_must_start_unsub = None

    async def _on_dp_must_start_by(self, _now) -> None:
        """Point-in-time callback: drive MUST_START_FORCED + release."""
        # Clear handle first — this fire is one-shot.
        self._dp_must_start_unsub = None
        try:
            from .energy_drain_precedence import DPState, try_transition
            from homeassistant.util import dt as dt_util
            carrier = getattr(self, "_dp_carrier", None)
            if carrier is not None and carrier.state == DPState.TRANSITIONED:
                try_transition(
                    carrier, DPState.MUST_START_FORCED, now_provider=dt_util.now,
                )
            tou_period = None
            try:
                tou_period = self._tou.get_current_period()
            except Exception:  # noqa: BLE001
                pass
            self._apply_dp_must_start_release(tou_period=tou_period)
            # Drive carrier to HOLD_ONLY after release fires so a
            # subsequent tick sees a clean idle state.
            if carrier is not None and carrier.state == DPState.MUST_START_FORCED:
                try_transition(
                    carrier, DPState.HOLD_ONLY, now_provider=dt_util.now,
                )
            self.hass.async_create_task(self._save_evse_state())
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "drain-precedence must-start-by fire callback raised (swallowed)",
                exc_info=True,
            )

    @callback
    def _arm_tou_boundary_listener(self) -> None:
        """v5.17.3 D1: arm at-boundary point-in-time listener.

        Fires ONE extra ``_async_decision_cycle`` at
        ``(next_boundary + TOU_BOUNDARY_TICK_DELAY_S)`` — real wall clock,
        NO now-override. The cycle evaluates the actual just-started
        period exactly like a periodic tick would; the +5s guard rides
        past the second-of-boundary edge so `get_current_period` reliably
        reports the new period. This boundary tick IS the first post-
        transition tick — it consumes `tou_transition_into` naturally, so
        the following periodic tick sees no edge.

        KILL SWITCH: if ``TOU_BOUNDARY_TICK_DELAY_S < 0`` this function
        returns EARLY without registering any listener — the feature is
        cleanly disabled with zero live code paths touched.

        Cancels any existing handle first so re-arm from the periodic
        path is idempotent (never double-fires at the same boundary).
        Reads the next boundary via
        ``TOURateEngine.get_next_period_change_dt`` (energy_tou.py). If
        no boundary is found within the lookahead window (pathological,
        e.g. flat-rate schedule) we simply do not arm and rely on the
        periodic timer.

        The callback `_on_tou_boundary` awaits one `_async_decision_cycle`
        and re-arms via this helper (chained self-healing arm). Re-arm
        computes the NEXT boundary from the post-transition wall clock,
        which naturally advances past the just-consumed one — no tight
        re-fire loop.
        """
        # KILL SWITCH — negative delay disables the feature entirely.
        if TOU_BOUNDARY_TICK_DELAY_S < 0:
            return
        # Runtime absence of helper (test bootstraps that predate v5.17.3):
        # silently no-op so those tests stay green. In production this would
        # indicate an HA API change — warn ONCE per process, then stay quiet.
        if async_track_point_in_time is None:
            global _ATP_ABSENCE_WARNED
            if not _ATP_ABSENCE_WARNED:
                _ATP_ABSENCE_WARNED = True
                _LOGGER.warning(
                    "TOU boundary tick unavailable: async_track_point_in_time "
                    "missing (HA API change?) — feature disabled"
                )
            return

        # Cancel any existing arm (idempotent re-arm).
        if self._tou_boundary_unsub is not None:
            try:
                self._tou_boundary_unsub()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("prior TOU boundary unsub raised", exc_info=True)
            self._tou_boundary_unsub = None

        try:
            from datetime import timedelta as _td
            from homeassistant.util import dt as dt_util
            next_boundary = self._tou.get_next_period_change_dt()
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "get_next_period_change_dt raised — boundary listener not armed",
                exc_info=True,
            )
            return
        if next_boundary is None:
            _LOGGER.debug(
                "No TOU boundary found within lookahead — periodic timer only"
            )
            return

        fire_at = next_boundary + _td(seconds=int(TOU_BOUNDARY_TICK_DELAY_S))
        # If the fire time is already in the past (arm invoked mid-tick
        # by a periodic self-heal race), skip — the next periodic tick or
        # next re-arm will pick up the following boundary. Prevents HA
        # raising for a past point-in-time.
        try:
            now_local = dt_util.now()
            if fire_at <= now_local:
                _LOGGER.debug(
                    "boundary fire time %s already in the past (now=%s) "
                    "— skipping this boundary",
                    fire_at, now_local,
                )
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            self._tou_boundary_unsub = async_track_point_in_time(
                self.hass, self._on_tou_boundary, fire_at,
            )
            _LOGGER.info(
                "at-boundary TOU tick armed: fire=%s boundary=%s delay=%ss",
                fire_at.isoformat(),
                next_boundary.isoformat(),
                int(TOU_BOUNDARY_TICK_DELAY_S),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "async_track_point_in_time failed for %s — periodic timer only",
                fire_at,
                exc_info=True,
            )
            self._tou_boundary_unsub = None

    async def _on_tou_boundary(self, _now) -> None:
        """Fire one at-boundary decision cycle (real wall clock), then re-arm.

        Real `dt_util.now()` — no synthetic clock. The +5s delay applied
        at arm-time already carries us past the boundary edge, so
        `get_current_period()` returns the NEW period.

        Re-arm happens in `finally` so a raised decision cycle can't
        leave the boundary listener dead (self-healing). Concurrency
        with the periodic tick is handled by the `_cycle_in_flight` guard
        inside `_async_decision_cycle`.
        """
        try:
            try:
                _LOGGER.info(
                    "at-boundary TOU tick: evaluating period=%s (real clock, +%ss)",
                    self._tou.get_current_period(),
                    int(TOU_BOUNDARY_TICK_DELAY_S),
                )
            except Exception:  # noqa: BLE001
                pass
            await self._async_decision_cycle()
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "at-boundary TOU decision cycle raised (swallowed)",
                exc_info=True,
            )
        finally:
            # Clear old handle — this one has fired.
            self._tou_boundary_unsub = None
            self._arm_tou_boundary_listener()

    async def _async_decision_cycle(self, _now=None) -> None:
        """Run the decision cycle (periodic OR at-boundary tick).

        v5.17.3 D1: also invoked once per TOU boundary via
        `_on_tou_boundary`. The `_cycle_in_flight` guard prevents the
        boundary tick and the periodic tick from running concurrently
        and racing shared strategy stamps (`_last_reserve_level_desired`,
        `_last_battery_decision`). The guard is a bool (event-loop is
        single-threaded, no asyncio.Lock needed): read-then-set is atomic
        because there's no `await` between them.
        """
        if not self._enabled:
            return
        if self._cycle_in_flight:
            _LOGGER.debug(
                "decision cycle already in flight — skipping re-entrant tick"
            )
            return
        self._cycle_in_flight = True
        try:
            await self._decision_cycle_body()
        finally:
            self._cycle_in_flight = False
            # v5.17.3 D1: self-heal the boundary listener from the periodic
            # path too — if a prior `_arm_tou_boundary_listener` failed
            # (transient exception, HA not-yet-running edge), each periodic
            # tick tries again. Cheap: the arm helper is idempotent and
            # no-ops when a valid handle is already stored or when the
            # kill-switch constant is negative.
            if (
                self._tou_boundary_unsub is None
                and TOU_BOUNDARY_TICK_DELAY_S >= 0
            ):
                self._arm_tou_boundary_listener()

    async def _decision_cycle_body(self) -> None:
        """Actual decision-cycle body (extracted for re-entrancy guard)."""
        self._maybe_reset_daily()

        try:
            # Get current TOU state
            period = self._tou.get_current_period()
            season = self._tou.get_season()

            # Check for period transition. v5.17.3 D1: when the at-boundary
            # tick fires (+5s after transition) THIS is the first tick that
            # sees the new period, so `_last_period` advances here and the
            # subsequent periodic tick sees no edge — no double-consume.
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
            # arbitrage_solar_attainability_ladder D1: also snapshot the
            # current EV charging load so BatteryStrategy._classify_attain_rung
            # can run rung-1 (solar redirect) projection. Wrapped in try/except
            # so a stale EVSE power sensor cannot break the battery decision.
            from homeassistant.util import dt as dt_util
            try:
                ev_load_w = self._ev.current_charging_load_w()
            except Exception:  # noqa: BLE001
                ev_load_w = None
            decision = self._battery.determine_mode(
                period, season,
                now=dt_util.now(),
                tou_transition_into=new_period,
                ev_load_w=ev_load_w,
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

            # Session B2b-ii — drain-precedence state machine + actuation.
            # Guarded by `is_dp_enabled(self)` per plan §127-135; when
            # disabled the ENTIRE block is skipped byte-identical to
            # pre-slice (mutation test (c) — disabled-silent). The tick
            # driver mutates the carrier + returns a decision; on the
            # HOLD_ONLY → HOLD_PRE_EVAL / HOLD_PRE_EVAL → TRANSITIONED
            # edges we call the sibling actuation methods. Reversion +
            # must-start-by fire are handled by the timer callback + the
            # charging-stopped branch below.
            try:
                self._dp_decision_tick(decision, period, ev_load_w)
            except _DPSkip:
                pass
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "drain-precedence tick raised (swallowed)", exc_info=True,
                )

            # v5.17.1 fix-up (B-MED-1): eager-persist the arbitrage chunk
            # latch on the CHARGE→HOLD transition. Without this, a reboot
            # in the window between the completion tick and the next
            # 15-min periodic save loses the latch → resurrects the
            # 2026-07-14 incident on restart. Cheap: single KV write,
            # only fires on the transition edge (not per-tick), reuses
            # `_save_evse_state` which already carries the latch payload.
            try:
                _completed_now = bool(
                    getattr(self._battery, "_arbitrage_chunk_completed", False)
                )
                _last_completed = getattr(
                    self, "_last_arbitrage_chunk_completed", False,
                )
                if _completed_now and not _last_completed:
                    self.hass.async_create_task(self._save_evse_state())
                    _LOGGER.info(
                        "Arbitrage chunk completed — eager latch persist "
                        "scheduled (reboot-safe HOLD on restart)"
                    )
                # v5.17.3 D2 (Tier-3 D-MED-2): mirror the eager-persist on the
                # TRUE→FALSE edge (chunk reset — normally fires from
                # `BatteryStrategy.reset_arbitrage_chunk` on TOU transition
                # INTO off_peak, energy_battery.py:2703). Without this, a
                # restart ≤15min after off_peak entry restores a stale
                # `completed=True` latch and would HOLD the fresh chunk
                # instead of charging. Same cheap KV write, edge-only.
                elif _last_completed and not _completed_now:
                    self.hass.async_create_task(self._save_evse_state())
                    _LOGGER.info(
                        "Arbitrage chunk reset — eager latch-clear persist "
                        "scheduled (fresh chunk safe on restart)"
                    )
                self._last_arbitrage_chunk_completed = _completed_now
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "eager latch persist scheduling failed (swallowed)",
                    exc_info=True,
                )

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
                # Fix-up B-CRIT-1 / B-CRIT-2 — BREAKER-SAFETY CHOKEPOINT.
                # Extracted into _execute_breaker_safe_dispatch so the
                # ordering invariant is directly unit-testable. See the
                # helper's docstring for the full invariant statement.
                (
                    pause_reason,
                    pause_requested,
                    grid_charge_intent,
                ) = await self._execute_breaker_safe_dispatch(decision, period)

                # Pass-2 fix-up — RESTORE pool TOU + EV TOU calls
                # collateral-deleted by the chokepoint refactor.
                # Extracted into `_dispatch_post_decision_tou_and_arbitrage`
                # so a coordinator-tick integration test can pin that
                # both calls actually fire AND `grid_charge_on` threads
                # live (leg-2 of the bidirectional breaker invariant).
                # See helper docstring for ordering recap.
                await self._dispatch_post_decision_tou_and_arbitrage(
                    period=period,
                    pause_reason=pause_reason,
                    pause_requested=pause_requested,
                    grid_charge_intent=grid_charge_intent,
                )

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
                else:
                    # D1 (INV-D1-RELEASE): release-only path runs
                    # unconditionally when the owning toggle is OFF so
                    # `_paused_by_grid_cap` cannot hold a device beyond
                    # the tick after grid-cap is disabled. Natural
                    # re-latch on toggle re-enable — the gated branch
                    # above re-populates from live inputs on the next
                    # decision cycle.
                    for action_spec in self._ev.release_all_grid_cap():
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
                #
                # evse-offpeak-fill-release D2: compute a TIME-anchored
                # "solar actively replenishing" flag for the high-SOC release
                # gate. Daytime-true / night-~0: the time-windowed expected
                # solar surplus (daylight-overlap pro-rated; ~0 at night) OR a
                # live charging battery (`battery_power_w > +100W`). NEVER raw
                # `solcast_remaining` (high all night = the original bug). At
                # night/no-solar this is False → only reserve-gated release →
                # the EV charges from guaranteed grid, not battery discharge.
                from .energy_const import (
                    DEFAULT_EV_SOLAR_REPLENISH_SURPLUS_PCT,
                )
                _now_phase = dt_util.now()
                try:
                    _surplus_pct = self._battery.expected_solar_surplus_now_pct(
                        _now_phase,
                    )
                except Exception:  # noqa: BLE001
                    _surplus_pct = 0.0
                _bat_pw = self._battery.battery_power_w
                solar_replenishing = (
                    _surplus_pct > DEFAULT_EV_SOLAR_REPLENISH_SURPLUS_PCT
                    or (_bat_pw is not None and _bat_pw > 100)
                )
                # EV charge-start dead-band fix D1 (+ fix-up A/B/D):
                # Compose the release floor from the battery emitter's
                # AUTHORITATIVE last commanded reserve — captures inclement
                # partial_hold + arbitrage/attain parks that a parallel
                # `current_offpeak_drain_target()` re-derivation is blind to.
                # And gate the F substitution + release-side sticky on
                # `off_peak` — outside off_peak the battery legitimately
                # discharges deep and the drain pause is the only backstop.
                # `_compose_release_floor` is the single-source composition
                # helper the mutation-anchored tests drive (Fix 5).
                from .energy_battery import compose_release_floor as _crf
                _release_floor, _is_offpeak = _crf(self._battery, period)
                drain_actions = self._ev.determine_battery_drain_actions(
                    battery_power_w=self._battery.battery_power_w,
                    battery_soc=self._battery.battery_soc,
                    soc_threshold=self._ev_battery_drain_soc,
                    reserve_soc=_release_floor,
                    solar_replenishing=solar_replenishing,
                    is_offpeak=_is_offpeak,
                )
                for action_spec in drain_actions:
                    await self._execute_service_action(action_spec)

                # v4.7.6 D2: EV fill-priority pause (gated by excess_solar
                # switch — same toggle controls both turn-ON and pause sides).
                if self._excess_solar_enabled:
                    from .energy_const import DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH
                    # evse-offpeak-fill-release D1: TIME-anchored day/night
                    # phase. `peak_ahead` = is a real peak still ahead before
                    # the next off_peak (midnight-safe, season-aware). Drives
                    # the mid_peak hold-vs-release; off_peak/peak release
                    # unconditionally inside the pool method. NONE solar input
                    # to the phase decision — cloud-proof.
                    try:
                        # A-L1: must yield None (not False) when no TOU engine,
                        # so the pool keeps its legacy always-hold for mid_peak
                        # instead of flipping to release. `is False` in the pool
                        # gate only releases on a genuine "no peak ahead".
                        peak_ahead = (
                            self._tou.peak_ahead_before_offpeak(_now_phase)
                            if self._tou is not None
                            else None
                        )
                    except Exception:  # noqa: BLE001
                        peak_ahead = None
                    # v4.7.6 fix-up B-M3: pass tick-snapshot, not live attr.
                    fp_actions = self._ev.determine_fill_priority_actions(
                        soc=self._battery.battery_soc,
                        remaining_forecast_kwh=self._battery.solcast_remaining,
                        tou_period=period,
                        soc_threshold=fill_priority_soc_tick,
                        excess_solar_kwh_threshold=self._excess_solar_kwh,
                        safety_margin_kwh=DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH,
                        peak_ahead=peak_ahead,
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
                else:
                    # D1 (INV-D1-RELEASE): release-only path for the
                    # EV fill-priority owner set. Runs unconditionally
                    # when excess-solar toggle is OFF so a device that
                    # was fill-priority-paused before the flip drains
                    # membership within one cycle.
                    for action_spec in self._ev.release_all_fill_priority():
                        await self._execute_service_action(action_spec)

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
                # D4 (2026-07-13 operator addition): plug determine_actions
                # now also runs the off_peak ensure-on branch (parity with
                # EVSE). Force-charge is threaded from EVPool so the plug
                # tier respects the same admin override.
                if self._ev_tou_enabled:
                    _fc_active = self._ev._is_force_charge_active()  # noqa: SLF001
                    # Fix 6d (A-LOW-1): thread `grid_charge_on` for L1
                    # parity with EVSE breaker-safety cede. Uses the same
                    # `grid_charge_intent` computed for the EVSE branch
                    # above so L1/L2 cede on the exact same signal.
                    plug_actions = self._smart_plugs.determine_actions(
                        period,
                        force_charge_active=_fc_active,
                        grid_charge_on=bool(grid_charge_intent),
                    )
                    for action_spec in plug_actions:
                        await self._execute_service_action(action_spec)
                else:
                    # D1 mirror (INV-D1-RELEASE): release-only path for
                    # the plug TOU owner set. Runs unconditionally when
                    # the EV TOU toggle is OFF so a plug paused before
                    # the flip drains membership within one cycle.
                    for action_spec in self._smart_plugs.release_all_tou():
                        await self._execute_service_action(action_spec)

                # v4.2.21: Smart plug battery drain protection
                # v4.3.4 fix: same kW/W unit fix as EV drain above.
                # v4.7.6 D1 mirror: reserve_soc threaded through.
                # v4.7.6 fix-up A-H1: propagate Force-Charge state from EVPool
                # so plug pause rules respect the same admin override.
                force_charge_active = self._ev._is_force_charge_active()
                # EV charge-start dead-band fix D2: L1/L2 parity — thread
                # the same effective release floor F used for the EV path
                # above, AND the `solar_replenishing` flag the EV path
                # already computes (the pre-existing plug-path gap: this
                # kwarg previously defaulted to False, so the plug's
                # `soc_recovered` gate could never fire and release was
                # reserve-only).
                plug_drain_actions = self._smart_plugs.determine_battery_drain_actions(
                    battery_power_w=self._battery.battery_power_w,
                    battery_soc=self._battery.battery_soc,
                    soc_threshold=self._ev_battery_drain_soc,
                    reserve_soc=_release_floor,
                    force_charge_active=force_charge_active,
                    solar_replenishing=solar_replenishing,
                    is_offpeak=_is_offpeak,
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
                else:
                    # D1 mirror (INV-D1-RELEASE): release-only path for
                    # the plug fill-priority owner set. Runs
                    # unconditionally when excess-solar toggle is OFF.
                    for action_spec in self._smart_plugs.release_all_fill_priority():
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

            # v5.15.x D1.5 — reversion sweep. READ-ONLY (W-6). Detects
            # shape-(c) silent revert (operator flipped switch in app).
            try:
                verifier = getattr(self, "_write_verifier", None)
                if verifier is not None:
                    await verifier.reversion_sweep()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "reversion sweep failed (swallowed)", exc_info=True,
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
        #
        # Session B2b-iii call-site audit — this second `_apply_evse_battery_hold`
        # call site (`_evaluate_battery`) is NOT diagnostic-only. It is
        # invoked from `evaluate()` on TOU-period transitions (energy.py:1118)
        # and its output feeds `CoordinatorAction`s dispatched to hardware
        # (energy.py:4519-4529 below). Symmetric DP wiring is inherent:
        # `_apply_evse_battery_hold` reads `self._dp_decision_soc` internally
        # in BOTH the update-in-place leg (energy.py:3224) and the append leg
        # (energy.py:3320), so any DP-elevated floor is composed here for
        # free — no additional wiring required. Evidence of consumption:
        # `evaluate()` returns actions to `CoordinatorManager._run_all_evaluations`
        # which dispatches them via the standard action pipeline.
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

    async def _execute_breaker_safe_dispatch(
        self,
        decision: dict[str, Any],
        period: str,
    ) -> tuple[str | None, bool, bool]:
        """Dispatch battery decision actions under the breaker-safety invariant.

        Fix-up B-CRIT-1 / B-CRIT-2 / B-HIGH-1 — BREAKER-SAFETY CHOKEPOINT.

        Physical invariant: a full ~20 kW Enphase grid charge + a
        charging EV (7.4 kW) + base (~5 kW) ≈ 134 A on the main breaker
        → trip risk. Therefore the bidirectional invariant:
          (1) NO ``charge_from_grid=True`` may be DISPATCHED on this
              tick until every EV is commanded paused (label="breaker")
              EARLIER in the same tick's dispatch sequence.
          (2) NO EV may be commanded ON while ``charge_from_grid`` is
              commanded OR ON in hardware (resume-side guard: lives in
              ``EVChargerController.determine_actions`` and
              ``.determine_arbitrage_actions`` via ``grid_charge_on``).

        Grid-charge intent is detected via ``decision["charge_from_grid"]``
        — set by ``BatteryStrategy._result()`` — which is phase-label-
        INDEPENDENT. This covers ALL grid-charge producers in one place:
        arbitrage CHARGE (rung-2), v5.3.8 ATTAIN (B-CRIT-2 was that the
        phase-label-based pause trigger excluded ATTAIN — fixed here),
        and any future rungs. Additionally we OR in a live-switch read
        of ``charge_from_grid`` so reboot-mid-charge cannot resume EVs
        before the decision catches up (B-HIGH-1).

        Returns:
            (pause_reason, pause_requested, grid_charge_intent) — passed
            to downstream call sites (TOU ensure-on, release path) so
            they observe the same grid-charge posture this tick.
        """
        from .energy_battery import ARBITRAGE_PHASE_CHARGE
        from .energy_const import DEFAULT_CHARGE_FROM_GRID_ENTITY

        decision_grid_charge = bool(decision.get("charge_from_grid", False))
        # Hardware-derived posture (B-HIGH-1 + Pass-2 P2-HIGH-1):
        # read the LIVE charge_from_grid switch. If it is ON regardless
        # of what the decision intends, the resume-side guards must
        # still hold EVs off (mirrors v5.3.8 attain's reboot-recovery
        # posture). A stale RAM flag is not authoritative.
        #
        # Pass-2 P2-HIGH-1 — FAIL CLOSED on Envoy blip + last-known-good
        # latch. The Envoy-unavailable decision shape at
        # energy_battery.py:~2405 omits `charge_from_grid` (defaults
        # False) and the live switch reads `unavailable`/`unknown` in
        # the SAME outage — both legs go False while the panel may
        # physically still be pulling 20 kW. Treat
        # `unavailable`/`unknown`/None reads as breaker-ON if we had a
        # prior on-tick (last-known-good latch, mirroring the capacity
        # LKG cache the prior fix-up added). On a clean read, update
        # the LKG.
        live_grid_charge_on = False
        try:
            # H1 (2026-07-13): LKG blip-latch is a COMMAND-state read
            # (does URA think the switch is ON right now?) — resolve to
            # the same leg the write dispatched to (W-5 coherence).
            eid = self._battery._get_entity(
                "charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY,
                role="write",
            )
            if eid:
                st = self.hass.states.get(eid)
                if st is None:
                    # No state object — treat as blip; fail closed if
                    # we ever saw it ON before.
                    if getattr(self, "_last_known_grid_charge_on", False):
                        live_grid_charge_on = True
                elif st.state == "on":
                    live_grid_charge_on = True
                    self._last_known_grid_charge_on = True
                elif st.state == "off":
                    live_grid_charge_on = False
                    self._last_known_grid_charge_on = False
                else:
                    # `unavailable`/`unknown`/anything else: FAIL CLOSED
                    # if last-known-good was ON. A transient blip during
                    # an actual grid charge must NOT release the resume
                    # guards.
                    if getattr(self, "_last_known_grid_charge_on", False):
                        live_grid_charge_on = True
                        _LOGGER.info(
                            "Energy: charge_from_grid read '%s' (blip) — "
                            "treating as ON (last-known-good latch) for "
                            "breaker-safety",
                            st.state,
                        )
        except Exception:  # noqa: BLE001 — defensive: registry blip
            # Registry blip == blip; fail closed on LKG.
            if getattr(self, "_last_known_grid_charge_on", False):
                live_grid_charge_on = True
        grid_charge_intent = decision_grid_charge or live_grid_charge_on

        arb_intent = getattr(self._battery, "_arbitrage_intent", None)
        arbitrage_charging_phase = (
            decision.get("arbitrage_phase") == ARBITRAGE_PHASE_CHARGE
        )
        # Grid-charge intent ALWAYS implies "breaker" regardless of
        # phase label — what threatens the panel is the 20 kW pull,
        # not the strategy's name for the operation.
        if grid_charge_intent:
            pause_reason: str | None = "breaker"
        elif arbitrage_charging_phase:
            # Defensive: future code path emits CHARGE phase without
            # setting charge_from_grid=True. Still pause for breaker.
            pause_reason = "breaker"
        elif arb_intent == "redirect":
            pause_reason = "redirect"
        else:
            pause_reason = None
        pause_requested = pause_reason is not None

        # ORDERING — the invariant. If a breaker-class pause is
        # requested, DISPATCH the EV-pause actions BEFORE dispatching
        # the battery decision actions (which may include
        # `switch.turn_on` for the charge_from_grid switch). Tests
        # `test_breaker_pause_ordering_*` pin this.
        if pause_reason == "breaker":
            breaker_actions = self._ev.determine_arbitrage_actions(
                arbitrage_charging=True,
                tou_period=period,
                pause_reason="breaker",
            )
            for action_spec in breaker_actions:
                await self._execute_service_action(action_spec)

        # Now dispatch the battery decision actions (may turn ON the
        # charge_from_grid switch — safe because EVs are already
        # commanded paused above).
        for action_spec in decision.get("actions", []):
            await self._execute_service_action(action_spec)
            # v5.15.x D1.3 — write-verification tap. READ-ONLY (W-6).
            try:
                await self._tap_write_verifier(action_spec, decision)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("write_verifier tap failed (swallowed)", exc_info=True)

        return pause_reason, pause_requested, grid_charge_intent

    async def _dispatch_post_decision_tou_and_arbitrage(
        self,
        period: str,
        pause_reason: str | None,
        pause_requested: bool,
        grid_charge_intent: bool,
    ) -> None:
        """Post-decision TOU + arbitrage release dispatch.

        Pass-2 fix-up — restores the pool TOU + EV TOU dispatch calls
        that the prior chokepoint refactor collateral-deleted, and
        wires leg-2 of the bidirectional breaker invariant (the
        `grid_charge_on` kwarg threaded into `EVChargerController
        .determine_actions`).

        Ordering recap (per the breaker invariant):
          1. breaker EV-pause  (inside `_execute_breaker_safe_dispatch`,
             pre-decision)
          2. decision["actions"]  (`charge_from_grid` switch.turn_on)
          3. EV/pool TOU determine_actions  (here — ensure-on
             suppressed when grid_charge_intent=True)
          4. arbitrage release / non-breaker pause  (here — `breaker`
             label already dispatched pre-decision, so skip to avoid
             double-dispatch)
        """
        # E2: Pool optimization (TOU pool-speed reduce/restore).
        pool_actions = self._pool.determine_actions(period)
        for action_spec in pool_actions:
            await self._execute_service_action(action_spec)

        # E2: EV charger control (TOU peak re-pause + v4.7.28 off-peak
        # ensure-on). Threaded `grid_charge_on` so the off-peak
        # ensure-on branch CANNOT turn an EV on while the battery is
        # grid-charging — leg-2 of the bidirectional breaker
        # invariant. Without this kwarg threaded live, the resume-side
        # guard added in the chokepoint refactor would be dead code.
        if self._ev_tou_enabled:
            ev_actions = self._ev.determine_actions(
                period, grid_charge_on=grid_charge_intent,
            )
            for action_spec in ev_actions:
                await self._execute_service_action(action_spec)
        else:
            # D1 (INV-D1-RELEASE): release-only path for `_paused_by_us`.
            # Runs unconditionally when the EV TOU toggle is OFF so an
            # EVSE paused before the flip drains membership within one
            # cycle. Cross-owner deferral inside `release_all_tou`
            # keeps stronger owners (drain/fill/grid-cap/arbitrage/
            # load-shed) in charge — TOU release must never override.
            release_actions = self._ev.release_all_tou()
            for action_spec in release_actions:
                await self._execute_service_action(action_spec)

        # Non-breaker arbitrage pause (rung-1 redirect) or release:
        # dispatch here. Breaker case was handled PRE-decision; we
        # still call the API on the release path so
        # `arbitrage_charging=False` can run its cleanup (label drop +
        # resume-policy eval).
        if pause_reason == "breaker":
            # Already dispatched pre-decision; skip to avoid
            # double-dispatch.
            return
        arb_actions = self._ev.determine_arbitrage_actions(
            arbitrage_charging=pause_requested,
            tou_period=period,
            pause_reason=pause_reason,
            grid_charge_on=grid_charge_intent,
        )
        for action_spec in arb_actions:
            await self._execute_service_action(action_spec)

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
            # B-CRIT-1 fix-up: disabling load-shedding mid-shed must
            # release all active tiers (defer-checks honor manual-off /
            # other owners) before zeroing the level, else
            # `_paused_by_load_shed` strands devices off permanently.
            if self._load_shedding_active_level > 0:
                self._release_all_active_tiers(reason="disabled")
            self._load_shedding_active_level = 0
            self._sustained_import_readings.clear()
            return

        # Only shed during peak and mid-peak
        if tou_period not in ("peak", "mid_peak"):
            # B-CRIT-1 fix-up: period flip peak/mid_peak → off_peak must
            # iterate active tiers and call `_execute_shed_action(activate=
            # False)` for each — without this, D1's `_paused_by_load_shed`
            # claims are never cleared (the de-escalate path only runs in
            # peak/mid_peak), and the off-peak resume that USED to rescue
            # the device is now suppressed by D1's deference. Net pre-cycle:
            # MORE stranded devices than before.
            if self._load_shedding_active_level > 0:
                _LOGGER.info("Energy: Load shedding released (off-peak)")
                self._release_all_active_tiers(reason="off_peak")
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

    def _release_all_active_tiers(self, *, reason: str) -> None:
        """Release every currently-active load-shed tier (top-down).

        load-shedding-correctness fix-up B-CRIT-1: shared helper for the
        off-peak short-circuit, the disabled short-circuit, and any other
        early-zero path. Iterates active tiers in REVERSE escalation order
        (highest tier first, mirroring the per-tick de-escalation order)
        and calls `_execute_shed_action(target, activate=False)` for each
        — `_execute_shed_action` already honors manual-off / other-owner
        precedence, so we don't duplicate that logic here.
        """
        level = self._load_shedding_active_level
        if level <= 0:
            return
        # Release from highest active tier down to tier 1.
        for tier_index in range(level - 1, -1, -1):
            try:
                target = LOAD_SHEDDING_PRIORITY[tier_index]
            except IndexError:
                continue
            try:
                self._execute_shed_action(target, activate=False)
            except Exception as e:  # noqa: BLE001 — defensive
                _LOGGER.warning(
                    "Energy: load-shed bulk-release of %s failed (%s) — "
                    "continuing remaining tiers (reason=%s)",
                    target, e, reason,
                )
        _LOGGER.info(
            "Energy: released %d load-shed tiers (reason=%s)", level, reason,
        )

    def _execute_shed_action(self, target: str, activate: bool) -> None:
        """Execute or release a load shedding action for the given target.

        Uses the subsystem controllers' action pattern — generates service call
        specs and executes them through _execute_service_action.

        load-shedding-correctness D1 + D3:
          * EV and smart-plug shed branches now mutate the dedicated
            `_paused_by_load_shed` set on each controller (not the
            TOU-shared `_paused_by_us`). The activate path is a proactive
            claim when the device is already off (mirrors v5.3.9 arbitrage
            claim-when-off).
          * Release defers to ANY other pause-owner that still claims
            the device (TOU, drain, fill-priority, grid-cap, arbitrage).
            For EVs this preserves DURABLE EV PHILOSOPHY (never resume
            an EV the battery-drain path wants paused).
          * Plug release respects operator-manual-off via the existing
            per-device ``_load_shed_was_on_at_shed`` map (fix-up
            C-HIGH-1; the prior `_pause_dispatch_ts` infra was written
            but never read — replaced).
          * Pool release discards `_original_speed` if the live speed
            no longer equals POOL_REDUCED_SPEED — operator-changed mid-
            shed wins.
        """
        actions: list[dict[str, Any]] = []
        # Tracks per-call release reason (consumed by D4 status surface).
        release_reason: str | None = None

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
                    # D3: manual-speed-change-wins. If live current_speed
                    # differs from the value we set during shed
                    # (POOL_REDUCED_SPEED), the operator overrode us —
                    # do NOT restore the stale `_original_speed`.
                    current = self._pool.current_speed
                    if current is not None and current != POOL_REDUCED_SPEED:
                        _LOGGER.info(
                            "Energy: Load shed pool release — respecting manual "
                            "speed change (live=%s != reduced=%s); "
                            "discarding stale original_speed",
                            current, POOL_REDUCED_SPEED,
                        )
                        self._pool._original_speed = None
                        self._pool._state = POOL_STATE_NORMAL
                        release_reason = "respect_manual_speed_change"
                    else:
                        actions.append({
                            "service": "number.set_value",
                            "target": self._pool._speed_entity,
                            "data": {"value": self._pool._original_speed},
                        })
                        self._pool._original_speed = None
                        self._pool._state = POOL_STATE_NORMAL
                        release_reason = release_reason or "auto"
        elif target == "ev":
            for evse_id, config in self._ev._evse.items():
                switch_entity = config.get("switch", "")
                if not switch_entity:
                    continue
                if activate:
                    state = self._ev._get_evse_state(evse_id)
                    if evse_id in self._ev._paused_by_load_shed:
                        # B-HIGH-2 fix-up: idempotency that respects
                        # operator manual-resume mid-shed. If we claimed
                        # the EVSE but live state is ON, the operator
                        # turned it back on — re-issue the shed action
                        # rather than blind-skipping (the prior code
                        # left the EVSE charging through peak).
                        if state["is_on"]:
                            actions.append({
                                "service": "switch.turn_off",
                                "target": switch_entity,
                                "data": {},
                            })
                            # Refresh was_on_at_shed: it WAS on at this
                            # (re-)claim. Release should restore.
                            self._ev._load_shed_was_on_at_shed[evse_id] = True
                            _LOGGER.info(
                                "Energy: Load shed re-claim EV %s "
                                "(operator-resumed mid-shed; turn_off)",
                                evse_id,
                            )
                        continue
                    if state["is_on"]:
                        actions.append({
                            "service": "switch.turn_off",
                            "target": switch_entity,
                            "data": {},
                        })
                        self._ev._paused_by_load_shed.add(evse_id)
                        # C-HIGH-1 fix-up: record live-state authority for
                        # release (was-on → eligible to be restored).
                        self._ev._load_shed_was_on_at_shed[evse_id] = True
                        _LOGGER.info(
                            "Energy: Load shed claim EV %s (turn_off)",
                            evse_id,
                        )
                    else:
                        # Proactive claim — switch already off (e.g. TOU
                        # holds it OR operator had it off). Record
                        # was_on_at_shed=False so release will NOT turn
                        # it on (manual-OFF respected by construction).
                        self._ev._paused_by_load_shed.add(evse_id)
                        self._ev._load_shed_was_on_at_shed[evse_id] = False
                        _LOGGER.debug(
                            "Energy: Load shed proactive-claim EV %s "
                            "(already off; peer owner; was_on=False)",
                            evse_id,
                        )
                else:
                    if evse_id in self._ev._paused_by_load_shed:
                        # Discard our claim first.
                        self._ev._paused_by_load_shed.discard(evse_id)
                        was_on_at_shed = self._ev._load_shed_was_on_at_shed.pop(
                            evse_id, False,
                        )
                        # Defer to any other pause-owner still claiming
                        # the device (DURABLE EV PHILOSOPHY includes
                        # `_paused_by_battery_drain`). Mirrors v5.3.9
                        # arbitrage release precedence (`:1387-1396`).
                        if (
                            evse_id in self._ev._paused_by_battery_drain
                            or evse_id in self._ev._paused_by_fill_priority
                            or evse_id in self._ev._paused_by_grid_cap
                            or evse_id in self._ev._paused_by_arbitrage
                            or evse_id in self._ev._paused_by_us
                        ):
                            _LOGGER.info(
                                "Energy: Load shed release EV %s — deferring "
                                "to other pause owner",
                                evse_id,
                            )
                            release_reason = release_reason or "deferred_to_other_owner"
                            continue
                        # C-HIGH-1 fix-up: manual-OFF wins by construction.
                        # If the EVSE wasn't on when we shed it, the device
                        # was either operator-off or TOU-off; do NOT turn
                        # it on at release.
                        if not was_on_at_shed:
                            _LOGGER.info(
                                "Energy: Load shed release EV %s — was off "
                                "at shed-time (manual-OFF / TOU-off), "
                                "not turning on",
                                evse_id,
                            )
                            release_reason = release_reason or "respect_manual_off"
                            continue
                        # Idempotency / safety: if the switch is already
                        # on (manual restore by operator), do not re-issue.
                        state = self._ev._get_evse_state(evse_id)
                        if state["is_on"]:
                            release_reason = release_reason or "auto"
                            continue
                        actions.append({
                            "service": "switch.turn_on",
                            "target": switch_entity,
                            "data": {},
                        })
                        release_reason = release_reason or "auto"
        elif target == "smart_plugs":
            for entity_id in self._smart_plugs._plugs:
                state = self.hass.states.get(entity_id)
                if state is None:
                    continue
                if activate:
                    if entity_id in self._smart_plugs._paused_by_load_shed:
                        # B-HIGH-2 fix-up: re-shed an operator-resumed plug
                        # rather than blind-skip. The plug is in our set
                        # but live state is ON — the prior code left it
                        # drawing through peak shed.
                        if state.state == "on":
                            actions.append({
                                "service": "switch.turn_off",
                                "target": entity_id,
                                "data": {},
                            })
                            self._smart_plugs._load_shed_was_on_at_shed[entity_id] = True
                            _LOGGER.info(
                                "Energy: Load shed re-claim plug %s "
                                "(operator-resumed mid-shed; turn_off)",
                                entity_id,
                            )
                        continue
                    if state.state == "on":
                        actions.append({
                            "service": "switch.turn_off",
                            "target": entity_id,
                            "data": {},
                        })
                        self._smart_plugs._paused_by_load_shed.add(entity_id)
                        # C-HIGH-1 fix-up: live-state authority. The dead
                        # `_pause_dispatch_ts` / `_observed_off_since_pause`
                        # writes the prior code emitted were never read on
                        # the release path — removed.
                        self._smart_plugs._load_shed_was_on_at_shed[entity_id] = True
                        _LOGGER.info(
                            "Energy: Load shed claim plug %s (turn_off)",
                            entity_id,
                        )
                    else:
                        # Proactive claim — already off (operator-off, or
                        # TOU-off). Record was_on_at_shed=False so release
                        # honors manual-OFF by construction.
                        self._smart_plugs._paused_by_load_shed.add(entity_id)
                        self._smart_plugs._load_shed_was_on_at_shed[entity_id] = False
                        _LOGGER.debug(
                            "Energy: Load shed proactive-claim plug %s "
                            "(already off; peer owner; was_on=False)",
                            entity_id,
                        )
                else:
                    if entity_id in self._smart_plugs._paused_by_load_shed:
                        # Discard our claim.
                        self._smart_plugs._paused_by_load_shed.discard(entity_id)
                        was_on_at_shed = self._smart_plugs._load_shed_was_on_at_shed.pop(
                            entity_id, False,
                        )
                        # Defer to other owners.
                        if (
                            entity_id in self._smart_plugs._paused_by_battery_drain
                            or entity_id in self._smart_plugs._paused_by_fill_priority
                            or entity_id in self._smart_plugs._paused_by_us
                        ):
                            _LOGGER.info(
                                "Energy: Load shed release plug %s — "
                                "deferring to other pause owner",
                                entity_id,
                            )
                            release_reason = release_reason or "deferred_to_other_owner"
                            continue
                        # C-HIGH-1 fix-up: manual-OFF wins by construction.
                        # Only restore plugs that were ON when we shed them.
                        # A proactive claim of an already-off plug (operator-
                        # off pre-shed, or manual-off-during-shed at claim
                        # time) must NOT be turned on at release.
                        if not was_on_at_shed:
                            _LOGGER.info(
                                "Energy: Load shed release plug %s — was off "
                                "at shed-time (manual-OFF / TOU-off), "
                                "not turning on",
                                entity_id,
                            )
                            release_reason = release_reason or "respect_manual_off"
                            continue
                        is_on_now = state.state == "on"
                        if not is_on_now:
                            # We shed it ON→OFF and live state is still off
                            # → restore.
                            actions.append({
                                "service": "switch.turn_on",
                                "target": entity_id,
                                "data": {},
                            })
                            release_reason = release_reason or "auto"
                        else:
                            # Live state is ON — operator manually re-enabled
                            # mid-shed. Idempotently skip; record reason.
                            _LOGGER.info(
                                "Energy: Load shed release plug %s — "
                                "respecting operator manual-on (state=on)",
                                entity_id,
                            )
                            release_reason = release_reason or "respect_manual_off"
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

        # load-shedding-correctness D4: record release reason + activity log.
        if not activate and release_reason is not None:
            self._last_release_reason = release_reason
            if release_reason in (
                "respect_manual_off",
                "respect_manual_speed_change",
                "deferred_to_other_owner",
            ):
                try:
                    activity_logger = self.hass.data.get(
                        _DOMAIN, {},
                    ).get("activity_logger")
                except Exception:  # noqa: BLE001 — defensive
                    activity_logger = None
                if activity_logger:
                    self.hass.async_create_task(
                        activity_logger.log(
                            coordinator="energy",
                            action="load_shed_release_" + release_reason,
                            description=(
                                f"Load shed release for {target}: "
                                f"{release_reason}"
                            ),
                            importance="notable",
                            details={
                                "target": target,
                                "reason": release_reason,
                                "level": self._load_shedding_active_level,
                            },
                        )
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

    async def _tap_write_verifier(
        self, action_spec: Any, decision: dict[str, Any]
    ) -> None:
        """v5.15.x D1.3 — post-dispatch tap; schedules a delayed
        oracle-vs-commanded compare. READ-ONLY (W-6).

        Fix-up A/B-HIGH-2: stamp the commanded ledger HERE using the
        ACTUAL dispatched value (captures the EVSE-hold ``max()`` raise
        at energy.py:2663-2678). The prior BatteryStrategy._result()
        stamping used the desired pre-hold value; verification then
        compared cloud vs an intent that URA never actually sent.

        Fix-up A-LOW-2: only tap when the action targets the configured
        battery entity id for that service — filters out unrelated
        switches/numbers/selects that happen to share the service name.
        """
        verifier = getattr(self, "_write_verifier", None)
        if verifier is None:
            return
        try:
            svc = action_spec.get("service")
            data = action_spec.get("data") or {}
            target = action_spec.get("target")
        except AttributeError:
            svc = getattr(action_spec, "service", None)
            data = getattr(action_spec, "data", {}) or {}
            target = getattr(action_spec, "target", None)
        if not svc:
            return
        try:
            from homeassistant.util import dt as dt_util
            _now = dt_util.utcnow()
        except Exception:  # noqa: BLE001
            _now = None
        # Resolve configured entity ids for each surface via the choke
        # point so operator overrides route correctly (mirrors
        # _build_entity_map keys).
        battery = getattr(self, "_battery", None)

        def _cfg(key: str, default: str | None = None) -> str | None:
            if battery is None:
                return None
            try:
                # H1 (2026-07-13): match the dispatched target on the same
                # leg the write was emitted to (cloud under cloud-first).
                return battery._get_entity(  # noqa: SLF001
                    key, default, role="write",
                )
            except Exception:  # noqa: BLE001
                return None

        if svc == "number.set_value":
            from .energy_const import DEFAULT_RESERVE_SOC_ENTITY
            reserve_eid = _cfg("reserve_soc_number", DEFAULT_RESERVE_SOC_ENTITY)
            if target and reserve_eid and target != reserve_eid:
                return
            value = data.get("value")
            # Stamp commanded ledger with the ACTUAL dispatched value
            # (post EVSE-hold max()).
            if battery is not None and value is not None:
                try:
                    _new = int(max(0, min(100, int(value))))
                    if battery._last_reserve_level != _new:  # noqa: SLF001
                        battery._last_reserve_level_at = _now  # noqa: SLF001
                    battery._last_reserve_level = _new  # noqa: SLF001
                except (TypeError, ValueError):
                    pass
            await verifier.schedule("reserve_soc", value, _now)
        elif svc in ("switch.turn_on", "switch.turn_off"):
            from .energy_const import DEFAULT_CHARGE_FROM_GRID_ENTITY
            cfg_eid = _cfg(
                "charge_from_grid", DEFAULT_CHARGE_FROM_GRID_ENTITY,
            )
            if target and cfg_eid and target != cfg_eid:
                return
            cmd_bool = (svc == "switch.turn_on")
            if battery is not None:
                if battery._last_charge_from_grid_command != cmd_bool:  # noqa: SLF001
                    battery._last_charge_from_grid_command_at = _now  # noqa: SLF001
                battery._last_charge_from_grid_command = cmd_bool  # noqa: SLF001
            await verifier.schedule("charge_from_grid", cmd_bool, _now)
        elif svc == "select.select_option":
            from .energy_const import DEFAULT_STORAGE_MODE_ENTITY
            cfg_eid = _cfg("storage_mode", DEFAULT_STORAGE_MODE_ENTITY)
            if target and cfg_eid and target != cfg_eid:
                return
            option = data.get("option")
            # Fix-up A-HIGH-2 storage_mode gate: only stamp/schedule
            # when the option was actually appended to actions (i.e. a
            # real select action ran).
            if option is None:
                return
            # H1 (2026-07-13): under cloud-first writes, the dispatched
            # option is a cloud LABEL ("Self-Consumption"). Normalize it
            # back to local vocab for the ledger + verify schedule so
            # `_compare` (which maps oracle cloud→local) stays coherent.
            from .energy_const import STORAGE_MODE_CLOUD_TO_LOCAL
            normalized_option = STORAGE_MODE_CLOUD_TO_LOCAL.get(
                str(option), option,
            )
            if battery is not None:
                if battery._last_storage_mode_command != normalized_option:  # noqa: SLF001
                    battery._last_storage_mode_command_at = _now  # noqa: SLF001
                battery._last_storage_mode_command = normalized_option  # noqa: SLF001
            await verifier.schedule("storage_mode", normalized_option, _now)

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
        # A/B-HIGH-3 fix-up: persist the load-shedding bundle each cycle so
        # a watchdog kill (no async_teardown — the dominant restart mode,
        # cf. v5.2.2 / 2026-06-09 incident) can still rebuild shed state on
        # startup. Throttled to write-on-change in `_save_load_shedding_level`
        # so steady-state cost is one no-op check, not a DB hit.
        await self._save_load_shedding_level()

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
        """Restore MetricBaselines from metric_baselines table.

        v5.12.0 SPAN circuit-identity re-key + RESUMABLE migration
        (v5.13.1 hotfix — was one-shot in v5.13.0):
        pre-migration rows carry scope=friendly_name. We back up each
        migrated row to `metric_baselines_pruned_backup` (v4.7.32 pattern)
        BEFORE rewriting scope to the rename-stable entity-registry
        unique_id, then INSERT a `_migration/circuit_scope_v2` sentinel
        (informational — records that the migration path executed at
        least once; does NOT gate subsequent boots).

        Boot-ordering resilience (v5.13.1): if the span_panel integration
        has not populated hass.states by the time
        `_restore_energy_baselines` runs, `discover_circuits()` returns
        no matches on boot N and rows fall through to
        `mig_unmatched_left`. On boot N+1 (once span_panel is up),
        the friendly→unique and entity_id→unique rewrite branches
        must run AGAIN so those rows finally migrate. The rewrite
        branches are per-row idempotent (branch 1 handles already-v2
        rows without rewriting) so re-running them is safe.

        Sentinel purpose: log verbosity only. First boot: INFO summary
        of what happened. Later boots: INFO when work happened this
        boot (progress made), DEBUG when nothing changed.

        Reversibility (extends v4.7.32):
            INSERT OR IGNORE INTO metric_baselines
              (coordinator_id, metric_name, scope, mean, variance,
               sample_count, last_updated)
            SELECT coordinator_id, metric_name, scope, mean, variance,
                   sample_count, last_updated
            FROM metric_baselines_pruned_backup
            WHERE coordinator_id='energy' AND metric_name='circuit_power';
            -- F12 rollback caveat: also delete the migration sentinel so
            -- the next boot's summary log reports the first-boot INFO line
            -- again (the sentinel is informational-only post-v5.13.1; the
            -- rewrite branches always run when rows resolve, gated per-row
            -- by the already-v2 short-circuit — not by the sentinel):
            DELETE FROM metric_baselines
              WHERE coordinator_id='energy'
                AND metric_name='_migration'
                AND scope='circuit_scope_v2';
            -- Any unique_id-keyed rows that were WRITTEN after migration
            -- (from live samples during the current release window) are
            -- harmless leftovers post-rollback: they simply won't have a
            -- friendly-scoped predecessor and the runtime chain in
            -- `_get_power_baseline` will keep using them. They can be
            -- DELETED manually if strict pre-migration parity is required.
        """
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

                # Ensure the reversible-backup table exists BEFORE the migration
                # path may need to write to it. Same shape as v4.7.32.
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS metric_baselines_pruned_backup ("
                    "coordinator_id TEXT, metric_name TEXT, scope TEXT, "
                    "mean REAL, variance REAL, sample_count INTEGER, "
                    "last_updated TEXT, pruned_at TEXT)"
                )

                # v5.12.0 F1: wrap the ENTIRE scan/backup/rewrite/DELETE/sentinel
                # + orphan-prune sequence in a single BEGIN IMMEDIATE transaction.
                # A crash mid-loop must leave the DB fully pre-migration (sentinel
                # unwritten → clean re-run on next boot). We keep the connection
                # open across the transaction so the aiosqlite driver's implicit
                # autocommit doesn't defeat atomicity.
                await conn.execute("BEGIN IMMEDIATE")
                # `circuit_baselines` and other counters are declared here so the
                # post-commit `restore_baselines` step (in-memory state must
                # lead disk state) can consume them.
                circuit_baselines: dict[str, MetricBaseline] = {}
                unmatched = 0
                stale_unmapped: list[str] = []
                mig_rewritten = 0
                mig_rewritten_from_entity_id = 0  # F2: separate counter
                mig_already_v2 = 0
                mig_unmatched_left: list[str] = []
                mig_attached_via_entity_id = 0  # F2: no rewrite, just attach
                try:
                    # v5.12.0 / v5.13.1: sentinel row indicates the
                    # friendly_name→unique_id migration path has executed at
                    # least once. It is INFORMATIONAL — it drives log
                    # verbosity only. The rewrite branches ALWAYS run when
                    # rows now resolve (per-row idempotent: branch 1
                    # short-circuits rows already keyed on unique_id
                    # without rewriting). This makes the migration resumable
                    # across the span_panel boot-ordering race (v5.13.1
                    # hotfix — v5.13.0 gated the rewrites on the sentinel,
                    # which permanently blocked re-migration if boot 1
                    # ran before span_panel populated hass.states).
                    # Private `_migration` metric_name is a reserved prefix
                    # (grep confirms no collisions).
                    cursor = await conn.execute(
                        "SELECT 1 FROM metric_baselines "
                        "WHERE coordinator_id='energy' "
                        "AND metric_name='_migration' AND scope='circuit_scope_v2'"
                    )
                    sentinel_row = await cursor.fetchone()
                    sentinel_present = sentinel_row is not None

                    # Build lookup maps for the already-migrated (unique_id)
                    # shape, the pre-migration (friendly_name) shape, and the
                    # entity_id fallback shape (F2 — some rows were written under
                    # scope=entity_id when unique_id was unresolved at save-time
                    # or when the operator saved under a rename-mode circuit).
                    # `circuit` dict keys are entity_ids at runtime.
                    uid_to_entity: dict[str, str] = {}
                    friendly_to_entity: dict[str, str] = {}
                    entity_id_set: set[str] = set()
                    # F5: detect duplicate friendly_names → WARN with both
                    # candidates, then preserve first-wins semantics.
                    friendly_first: dict[str, str] = {}
                    for eid, circuit in self._circuits._circuits.items():
                        if circuit.unique_id:
                            uid_to_entity[circuit.unique_id] = eid
                        if circuit.friendly_name:
                            fname = circuit.friendly_name
                            if fname in friendly_first:
                                _LOGGER.warning(
                                    "Duplicate SPAN friendly_name '%s' shared by "
                                    "circuits %s and %s — first-wins for baseline "
                                    "restore may attach to the wrong circuit; "
                                    "rename one in the SPAN app to disambiguate",
                                    fname, friendly_first[fname], eid,
                                )
                            else:
                                friendly_first[fname] = eid
                                friendly_to_entity[fname] = eid
                        entity_id_set.add(eid)

                    cursor = await conn.execute("""
                        SELECT metric_name, scope, mean, variance,
                               sample_count, last_updated
                        FROM metric_baselines
                        WHERE coordinator_id = 'energy'
                    """)
                    rows = await cursor.fetchall()
                    from datetime import datetime as _dt, timezone as _tz
                    _migrated_at = _dt.now(_tz.utc).isoformat()
                    for row in rows:
                        # Skip the sentinel itself.
                        if row["metric_name"] == "_migration":
                            continue
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
                            scope = row["scope"]
                            # 1. Already-v2 shape: scope matches a live unique_id.
                            if scope in uid_to_entity:
                                eid = uid_to_entity[scope]
                                # Rewrite in-memory scope so subsequent
                                # save-loops persist under unique_id even if the
                                # circuit's baseline gets re-fetched. Baseline
                                # was constructed with scope=row["scope"] which
                                # already IS the unique_id here — no-op reassign.
                                baseline.scope = scope
                                circuit_baselines[eid] = baseline
                                mig_already_v2 += 1
                            # 2. Pre-migration shape: scope matches a friendly_name
                            #    that has a resolvable unique_id → rewrite the row.
                            #    v5.13.1: no sentinel gate — this branch runs on
                            #    EVERY boot so rows that were unresolvable on a
                            #    prior boot (span_panel not yet up) get migrated
                            #    once the registry resolves.
                            elif (
                                scope in friendly_to_entity
                                and self._circuits._circuits[
                                    friendly_to_entity[scope]
                                ].unique_id
                            ):
                                eid = friendly_to_entity[scope]
                                new_uid = self._circuits._circuits[eid].unique_id
                                # Back up pre-migration row FIRST (safety).
                                await conn.execute(
                                    "INSERT INTO metric_baselines_pruned_backup "
                                    "SELECT coordinator_id, metric_name, scope, mean, "
                                    "variance, sample_count, last_updated, ? "
                                    "FROM metric_baselines "
                                    "WHERE coordinator_id='energy' "
                                    "AND metric_name='circuit_power' AND scope = ?",
                                    (_migrated_at, scope),
                                )
                                # Rewrite: INSERT OR REPLACE at new scope, DELETE old.
                                await conn.execute(
                                    "INSERT OR REPLACE INTO metric_baselines "
                                    "(coordinator_id, metric_name, scope, mean, "
                                    " variance, sample_count, last_updated) "
                                    "VALUES ('energy', 'circuit_power', ?, ?, ?, ?, ?)",
                                    (
                                        new_uid,
                                        row["mean"],
                                        row["variance"],
                                        row["sample_count"],
                                        row["last_updated"],
                                    ),
                                )
                                await conn.execute(
                                    "DELETE FROM metric_baselines "
                                    "WHERE coordinator_id='energy' "
                                    "AND metric_name='circuit_power' AND scope = ?",
                                    (scope,),
                                )
                                baseline.scope = new_uid
                                circuit_baselines[eid] = baseline
                                mig_rewritten += 1
                            # 2b. F2 (Review B-HIGH-1): scope matches a live
                            #     entity_id. Rows written under scope=entity_id
                            #     (unique_id unresolved at save-time, or saved
                            #     while operator was mid-rename) would otherwise
                            #     be orphaned. Attach directly; if a unique_id
                            #     now resolves AND the migration is running,
                            #     upgrade the row via the same backup→rewrite→
                            #     delete path used by branch 2.
                            elif scope in entity_id_set:
                                eid = scope
                                circuit = self._circuits._circuits[eid]
                                # v5.13.1: no sentinel gate — upgrade whenever
                                # a unique_id now resolves for an entity_id-
                                # scoped row (was gated on `not migration_done`
                                # in v5.13.0, which stranded rows if the boot-1
                                # discovery race hit).
                                if circuit.unique_id:
                                    new_uid = circuit.unique_id
                                    await conn.execute(
                                        "INSERT INTO metric_baselines_pruned_backup "
                                        "SELECT coordinator_id, metric_name, scope, mean, "
                                        "variance, sample_count, last_updated, ? "
                                        "FROM metric_baselines "
                                        "WHERE coordinator_id='energy' "
                                        "AND metric_name='circuit_power' AND scope = ?",
                                        (_migrated_at, scope),
                                    )
                                    await conn.execute(
                                        "INSERT OR REPLACE INTO metric_baselines "
                                        "(coordinator_id, metric_name, scope, mean, "
                                        " variance, sample_count, last_updated) "
                                        "VALUES ('energy', 'circuit_power', ?, ?, ?, ?, ?)",
                                        (
                                            new_uid,
                                            row["mean"],
                                            row["variance"],
                                            row["sample_count"],
                                            row["last_updated"],
                                        ),
                                    )
                                    await conn.execute(
                                        "DELETE FROM metric_baselines "
                                        "WHERE coordinator_id='energy' "
                                        "AND metric_name='circuit_power' AND scope = ?",
                                        (scope,),
                                    )
                                    baseline.scope = new_uid
                                    circuit_baselines[eid] = baseline
                                    mig_rewritten_from_entity_id += 1
                                else:
                                    # No unique_id available (or migration
                                    # already done) — attach in place; on save
                                    # the runtime `_get_power_baseline` chain
                                    # will re-persist under entity_id.
                                    circuit_baselines[eid] = baseline
                                    mig_attached_via_entity_id += 1
                            # 3. "Unmapped Tab" stale scopes → v4.7.32 auto-prune.
                            elif "Unmapped Tab" in str(row["scope"]):
                                stale_unmapped.append(scope)
                            # 4. Unknown scope, no resolution → leave in place at
                            #    INFO. Covers the 3 known orphans (`'Battery Power'`,
                            #    `'Span Left Subpanel Power'`, `'Span Left Unknown
                            #    Power'`) per plan D3.4. Manual DELETE remains the
                            #    exit ramp; we no longer WARN each boot.
                            else:
                                mig_unmatched_left.append(scope)
                                # v5.13.1 review MEDIUM-1: INFO on first boot
                                # only; DEBUG once the sentinel exists so the
                                # 3 known permanent orphans don't emit 3 INFO
                                # lines every boot forever.
                                _unmatched_log = (
                                    _LOGGER.debug if sentinel_present
                                    else _LOGGER.info
                                )
                                _unmatched_log(
                                    "Circuit baseline '%s' has no matching circuit "
                                    "(kept in place; manual DELETE if intentionally orphaned)",
                                    scope,
                                )
                    # F1 note: `restore_baselines` (in-memory) is deferred until
                    # AFTER commit — disk state leads memory state so a crash
                    # doesn't leave RAM promising rows the DB doesn't have.

                    # Insert / refresh the migration sentinel. Informational
                    # only — never gates the rewrite branches. v5.13.1 review
                    # LOW-1: written when absent OR when rewrite work happened
                    # this boot (keeps last_updated = most-recent productive
                    # pass), skipped on steady-state boots (write-volume
                    # discipline: zero needless writes per boot).
                    # (computed inline — the aggregate `_rewrote_this_boot`
                    # is only assembled after the transaction block)
                    _sentinel_work = bool(
                        mig_rewritten
                        or mig_rewritten_from_entity_id
                        or stale_unmapped
                    )
                    if not sentinel_present or _sentinel_work:
                        await conn.execute(
                            "INSERT OR REPLACE INTO metric_baselines "
                            "(coordinator_id, metric_name, scope, mean, variance, "
                            " sample_count, last_updated) "
                            "VALUES ('energy', '_migration', 'circuit_scope_v2', "
                            " 0, 0, 1, ?)",
                            (_migrated_at,),
                        )

                    # F1: Unmapped-Tab prune folded into the same transaction so
                    # crash-mid-prune leaves the DB pre-migration.
                    if stale_unmapped:
                        # Reversible prune: copy each row to a backup table BEFORE
                        # deleting, so a bad prune can be undone with
                        # (use OR IGNORE so a scope that has since relearned is
                        # NOT clobbered — Review B1):
                        #   INSERT OR IGNORE INTO metric_baselines
                        #     (coordinator_id,metric_name,scope,mean,variance,
                        #      sample_count,last_updated)
                        #   SELECT coordinator_id,metric_name,scope,mean,variance,
                        #      sample_count,last_updated
                        #   FROM metric_baselines_pruned_backup;
                        _pruned_at = _migrated_at
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

                    # F1: single commit — everything above is one atomic write.
                    await conn.commit()
                except Exception:
                    # F1: crash mid-loop must leave the DB fully pre-migration.
                    # WARN — not debug-swallow — so operator sees a broken
                    # migration attempt. Re-raise so the outer except also logs.
                    try:
                        await conn.rollback()
                    except Exception as _rb_err:  # noqa: BLE001
                        _LOGGER.warning(
                            "SPAN scope migration: rollback also failed: %s",
                            _rb_err,
                        )
                    _LOGGER.warning(
                        "SPAN scope migration aborted mid-transaction; "
                        "rolled back to pre-migration state (next boot will retry)"
                    )
                    raise

                # F1: disk state is now durable — safe to update in-memory state.
                if circuit_baselines:
                    self._circuits.restore_baselines(circuit_baselines)

                # F9 / v5.13.1: summary log verbosity.
                #   First boot (sentinel wasn't present): always emit — INFO
                #     if any work happened, DEBUG with '(first boot; nothing
                #     to migrate)' suffix otherwise.
                #   Later boots (sentinel present): INFO when progress was
                #     made this boot (rewrite branches did work), DEBUG when
                #     nothing changed. This makes a boot-N+1 completion of
                #     the migration (after a boot-1 discovery race) visible
                #     without flooding steady-state boots.
                _rewrote_this_boot = (
                    mig_rewritten
                    or mig_rewritten_from_entity_id
                    or stale_unmapped
                )
                _did_work = (
                    _rewrote_this_boot
                    or mig_already_v2
                    or mig_attached_via_entity_id
                    or mig_unmatched_left
                )
                summary_msg = (
                    "SPAN scope migration: %d migrated, "
                    "%d rewritten-from-entity_id, %d attached-via-entity_id, "
                    "%d already-v2, %d unmatched-left-in-place (%s), "
                    "%d unmapped-pruned"
                )
                summary_args = (
                    mig_rewritten,
                    mig_rewritten_from_entity_id,
                    mig_attached_via_entity_id,
                    mig_already_v2,
                    len(mig_unmatched_left),
                    ", ".join(repr(s) for s in mig_unmatched_left) or "-",
                    len(stale_unmapped),
                )
                if not sentinel_present:
                    # First boot on this DB.
                    if _did_work:
                        _LOGGER.info(summary_msg, *summary_args)
                    else:
                        _LOGGER.debug(
                            summary_msg + " (first boot; nothing to migrate)",
                            *summary_args,
                        )
                else:
                    # Subsequent boot — only INFO when progress was made.
                    if _rewrote_this_boot:
                        _LOGGER.info(summary_msg, *summary_args)
                    else:
                        _LOGGER.debug(summary_msg, *summary_args)
                if stale_unmapped:
                    _LOGGER.info(
                        "SPAN: pruned %d orphaned 'Unmapped Tab' circuit baselines "
                        "(backed up to metric_baselines_pruned_backup; reversible). "
                        "Affected scopes will relearn under current names.",
                        len(stale_unmapped),
                    )
                # v5.12.0: `unmatched` is retained for shape parity but is
                # always 0 — orphan rows are now classified into
                # `mig_unmatched_left` (INFO, kept in place) instead of
                # WARNed each boot. F6: restored-count derived from a fresh
                # SELECT that excludes the sentinel — accounting matches
                # the number of real baselines actually in the table.
                cursor = await conn.execute(
                    "SELECT COUNT(*) FROM metric_baselines "
                    "WHERE coordinator_id='energy' AND metric_name != '_migration'"
                )
                _row = await cursor.fetchone()
                _restored_ct = int(_row[0]) if _row else 0
                _LOGGER.info(
                    "Restored %d energy baselines (peak_import: %d samples)",
                    _restored_ct - len(mig_unmatched_left),
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
        # v5.17.3 D1: cancel the anticipatory TOU-boundary listener too.
        # Stored separately from `_unsub_listeners` (mirrors the periodic
        # timer pattern) so re-setup after teardown can re-arm cleanly.
        if self._tou_boundary_unsub is not None:
            try:
                self._tou_boundary_unsub()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "TOU boundary unsub raised (swallowed)", exc_info=True,
                )
            self._tou_boundary_unsub = None
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
        # v5.15.x fix-up B-HIGH-3 (Bug Class #38) — cancel any pending
        # WriteVerifier delayed checks so their async_call_later handles
        # do not fire after the coordinator is gone.
        try:
            verifier = getattr(self, "_write_verifier", None)
            if verifier is not None:
                verifier.cancel_all()
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "write_verifier.cancel_all raised (swallowed)", exc_info=True,
            )
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

    # ------------------------------------------------------------------
    # EVSE Drain-Precedence setters (Session B1) — knob entity → coord
    # ------------------------------------------------------------------
    # Called by the Switch / Number / Select entities BEFORE their
    # `async_update_entry` writeback, so the next decision tick reads
    # the fresh value even if the CM options-update listener is still in
    # flight. Runtime readers (wired by Session B2) will read these attrs
    # via `is_dp_enabled()` etc.
    @property
    def dp_enabled(self) -> bool:
        return self._dp_enabled

    def set_dp_enabled(self, value: bool) -> None:
        self._dp_enabled = bool(value)
        _LOGGER.info("Drain-precedence enabled=%s", bool(value))

    @property
    def dp_eval_delay_min(self) -> int:
        return self._dp_eval_delay_min

    def set_dp_eval_delay_min(self, value: int) -> None:
        self._dp_eval_delay_min = int(value)
        _LOGGER.info("Drain-precedence eval delay set to %d min", int(value))

    @property
    def dp_margin_min(self) -> int:
        return self._dp_margin_min

    def set_dp_margin_min(self, value: int) -> None:
        self._dp_margin_min = int(value)
        _LOGGER.info("Drain-precedence margin set to %d min", int(value))

    @property
    def dp_must_start_by_min(self) -> int:
        return self._dp_must_start_by_min

    def set_dp_must_start_by_min(self, value: int) -> None:
        self._dp_must_start_by_min = int(value)
        _LOGGER.info(
            "Drain-precedence must-start-by set to %d min past midnight",
            int(value),
        )

    @property
    def dp_needed_kwh_garage_a(self) -> float:
        return self._dp_needed_kwh_garage_a

    def set_dp_needed_kwh_garage_a(self, value: float) -> None:
        self._dp_needed_kwh_garage_a = float(value)
        _LOGGER.info(
            "Drain-precedence needed_kwh (garage A) set to %.2f kWh", float(value)
        )

    @property
    def dp_needed_kwh_garage_b(self) -> float:
        return self._dp_needed_kwh_garage_b

    def set_dp_needed_kwh_garage_b(self, value: float) -> None:
        self._dp_needed_kwh_garage_b = float(value)
        _LOGGER.info(
            "Drain-precedence needed_kwh (garage B) set to %.2f kWh", float(value)
        )

    @property
    def dp_house_load_source(self) -> str:
        return self._dp_house_load_source

    def set_dp_house_load_source(self, value: str) -> None:
        from .energy_const import (
            DP_HOUSE_LOAD_SOURCES,
            CONF_DP_HOUSE_LOAD_SOURCE as _DEFAULT,
        )
        v = str(value)
        if v not in DP_HOUSE_LOAD_SOURCES:
            _LOGGER.warning(
                "Drain-precedence house_load_source %r not in %s — coerced to %s",
                v, list(DP_HOUSE_LOAD_SOURCES), _DEFAULT,
            )
            v = _DEFAULT
        self._dp_house_load_source = v
        _LOGGER.info("Drain-precedence house_load_source set to %s", v)

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
    def battery_full_time_attrs(self) -> dict:
        """H2 diagnostic attrs for the Battery Full Time sensor.

        v5.16.1 fix-up follow-up (Bug Class #55): the predictor computed
        these (basis, current_charge_rate_kw, taper_band, taper_note,
        missing_input, ...) but no entity surfaced them — the sensor had
        no extra_state_attributes at all.
        """
        return dict(getattr(self._predictor, "_battery_full_time_attrs", {}) or {})

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
            # load-shedding-correctness D1: dedicated load-shed owner.
            if bool(self._smart_plugs._paused_by_load_shed):
                plugs_under_shed.update(
                    self._smart_plugs._paused_by_load_shed,
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

    # ------------------------------------------------------------------
    # v5.7.1 — Energy Saver Pre-Cool (EC-owned operator surfaces).
    # Replaces the retired solar_banking_enabled property/setter.
    # ------------------------------------------------------------------

    @property
    def energy_precool_enabled(self) -> bool:
        """Whether Energy Saver Pre-Cool is enabled (operator master toggle).

        Read by HVACPredictor._is_energy_precool_enabled() to short-
        circuit the unified pre-cool branch in _check_pre_conditioning
        when the operator flips this OFF from the EC device card.
        """
        return self._energy_precool_enabled

    @energy_precool_enabled.setter
    def energy_precool_enabled(self, value: bool) -> None:
        """Set Energy Saver Pre-Cool master enable."""
        self._energy_precool_enabled = bool(value)
        _LOGGER.info("Energy Saver Pre-Cool master: %s", value)

    @property
    def energy_precool_offset(self) -> float:
        """Operator-configured pre-cool offset (°F; sign-convention negative)."""
        return self._energy_precool_offset

    @energy_precool_offset.setter
    def energy_precool_offset(self, value: float) -> None:
        """Set Energy Saver Pre-Cool offset (°F)."""
        try:
            self._energy_precool_offset = float(value)
        except (TypeError, ValueError):
            from .hvac_const import DEFAULT_ENERGY_PRECOOL_OFFSET
            self._energy_precool_offset = DEFAULT_ENERGY_PRECOOL_OFFSET
        _LOGGER.info(
            "Energy Saver Pre-Cool offset: %.2f°F",
            self._energy_precool_offset,
        )

    @property
    def energy_precool_scope(self) -> str:
        """Operator-configured pre-cool scope (one of three values)."""
        return self._energy_precool_scope

    @energy_precool_scope.setter
    def energy_precool_scope(self, value: str) -> None:
        """Set Energy Saver Pre-Cool scope. Invalid values fall back to default."""
        from .hvac_const import (
            DEFAULT_ENERGY_PRECOOL_SCOPE,
            ENERGY_PRECOOL_SCOPE_VALUES,
        )
        if value in ENERGY_PRECOOL_SCOPE_VALUES:
            self._energy_precool_scope = value
        else:
            self._energy_precool_scope = DEFAULT_ENERGY_PRECOOL_SCOPE
        _LOGGER.info(
            "Energy Saver Pre-Cool scope: %s", self._energy_precool_scope,
        )

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
        """Whether any load shedding is active (pool reduced, EVs paused, plugs paused).

        load-shedding-correctness D1: now reads from `_paused_by_load_shed`
        (the dedicated load-shed pause-owner) instead of `_paused_by_us`
        (the TOU pause-owner). Pre-fix this property would report True
        for any TOU-paused EVSE/plug — wrong semantics.
        """
        return (
            self._pool.state != "normal"
            or bool(self._ev._paused_by_load_shed)
            or bool(self._smart_plugs._paused_by_load_shed)
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
            # load-shedding-correctness D4: dedicated load_shed pause-owner
            # surface + diagnostics so dashboards can distinguish a load-
            # shed pause from a TOU pause on the same device.
            "paused_by_load_shed_ev": list(self._ev._paused_by_load_shed),
            "paused_by_load_shed_plugs": list(
                self._smart_plugs._paused_by_load_shed
            ),
            "pool_pre_shed_speed": self._pool._original_speed,
            "last_release_reason": self._last_release_reason,
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

"""Energy Coordinator — manages battery, pool, EV, TOU optimization, solar awareness.

Sub-Cycle E1: TOU Engine + Battery Strategy
Sub-Cycle E2: Pool + EV + Smart Plugs
Priority 40 (higher than HVAC at 30, lower than Safety at 100).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
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
from .energy_forecast import AccuracyTracker, DailyEnergyPredictor
from .energy_pool import EVChargerController, PoolOptimizer, SmartPlugController
from .energy_const import (
    CONF_ENERGY_ARBITRAGE_ENABLED,
    CONF_ENERGY_ARBITRAGE_SOC_TARGET,
    CONF_ENERGY_ARBITRAGE_SOC_TRIGGER,
    CONF_ENERGY_BATTERY_POWER_ENTITY,
    CONF_ENERGY_BATTERY_SOC_ENTITY,
    CONF_ENERGY_CHARGE_FROM_GRID_ENTITY,
    CONF_ENERGY_CONSTRAINT_COAST_OFFSET,
    CONF_ENERGY_CONSTRAINT_PRECOOL_OFFSET,
    CONF_ENERGY_CONSTRAINT_PREHEAT_OFFSET,
    CONF_ENERGY_CONSTRAINT_SHED_OFFSET,
    CONF_ENERGY_EXCESS_SOLAR_ENABLED,
    CONF_ENERGY_EXCESS_SOLAR_KWH,
    CONF_ENERGY_EXCESS_SOLAR_SOC,
    CONF_ENERGY_GRID_ENABLED_ENTITY,
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
    DEFAULT_ARBITRAGE_SOC_TRIGGER,
    DEFAULT_CONSTRAINT_COAST_OFFSET,
    DEFAULT_CONSTRAINT_PRECOOL_OFFSET,
    DEFAULT_CONSTRAINT_PREHEAT_OFFSET,
    DEFAULT_CONSTRAINT_SHED_OFFSET,
    DEFAULT_CONSUMPTION_TODAY_ENTITY,
    DEFAULT_DECISION_INTERVAL_MINUTES,
    DEFAULT_EXCESS_SOLAR_KWH_THRESHOLD,
    DEFAULT_EXCESS_SOLAR_SOC_THRESHOLD,
    DEFAULT_LIFETIME_BATTERY_CHARGED_ENTITY,
    DEFAULT_LIFETIME_BATTERY_DISCHARGED_ENTITY,
    DEFAULT_LIFETIME_CONSUMPTION_ENTITY,
    DEFAULT_LIFETIME_NET_EXPORT_ENTITY,
    DEFAULT_LIFETIME_NET_IMPORT_ENTITY,
    DEFAULT_LIFETIME_PRODUCTION_ENTITY,
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
        solar_classification_mode: str = "automatic",
        custom_solar_thresholds: dict[str, float] | None = None,
    ) -> None:
        """Initialize Energy Coordinator."""
        super().__init__(
            hass,
            coordinator_id="energy",
            name="Energy Coordinator",
            priority=40,
        )
        self._decision_interval = decision_interval

        # Try loading TOU rates from JSON file, fall back to PEC defaults
        from .energy_const import DEFAULT_TOU_RATE_FILE
        config_dir = hass.config.path("")
        self._tou = TOURateEngine.from_json_file(config_dir, DEFAULT_TOU_RATE_FILE)

        # Build off-peak drain targets from config
        ec = entity_config or {}
        offpeak_drain_targets = {
            "excellent": ec.get(CONF_ENERGY_OFFPEAK_DRAIN_EXCELLENT, DEFAULT_OFFPEAK_DRAIN_EXCELLENT),
            "good": ec.get(CONF_ENERGY_OFFPEAK_DRAIN_GOOD, DEFAULT_OFFPEAK_DRAIN_GOOD),
            "moderate": ec.get(CONF_ENERGY_OFFPEAK_DRAIN_MODERATE, DEFAULT_OFFPEAK_DRAIN_MODERATE),
            "poor": ec.get(CONF_ENERGY_OFFPEAK_DRAIN_POOR, DEFAULT_OFFPEAK_DRAIN_POOR),
        }

        self._battery = BatteryStrategy(
            hass,
            reserve_soc=reserve_soc,
            entity_config=self._build_entity_map(entity_config),
            solar_classification_mode=solar_classification_mode,
            custom_solar_thresholds=custom_solar_thresholds,
            offpeak_drain_targets=offpeak_drain_targets,
            arbitrage_enabled=ec.get(CONF_ENERGY_ARBITRAGE_ENABLED, False),
            arbitrage_soc_trigger=ec.get(CONF_ENERGY_ARBITRAGE_SOC_TRIGGER, DEFAULT_ARBITRAGE_SOC_TRIGGER),
            arbitrage_soc_target=ec.get(CONF_ENERGY_ARBITRAGE_SOC_TARGET, DEFAULT_ARBITRAGE_SOC_TARGET),
        )
        # E2: Pool, EV, Smart Plugs
        self._pool = PoolOptimizer(hass, pool_speed_entity=pool_speed_entity)
        self._ev = EVChargerController(hass, evse_config=evse_config)
        self._smart_plugs = SmartPlugController(hass, plug_entities=smart_plug_entities)

        # v3.11.0: Configured weather entity (for DB logging)
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

        # E3: Circuit monitoring + generator
        self._circuits = SPANCircuitMonitor(hass)
        self._generator = GeneratorMonitor(hass)

        # E4: Billing + cost tracking
        self._billing = CostTracker(hass, self._tou)

        # E5: Forecasting + prediction
        weather_ent = (entity_config or {}).get(CONF_ENERGY_WEATHER_ENTITY)
        self._predictor = DailyEnergyPredictor(hass, weather_entity=weather_ent)
        self._accuracy = AccuracyTracker()

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

        self._decision_timer_unsub = None

        # Observation mode: sensors compute, no actions executed
        self._observation_mode: bool = False

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

        # Envoy availability tracking
        self._envoy_unavailable_count: int = 0
        self._envoy_last_available: str | None = None
        # Cross-check: last logged divergence (avoid log spam)
        self._last_crosscheck_hour: int = -1
        # Throttle peak import DB saves to once per hour
        self._last_peak_save_hour: int = -1
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

    def _build_entity_map(self, config: dict[str, str] | None) -> dict[str, str]:
        """Build entity mapping from config keys to battery strategy keys."""
        if not config:
            return {}
        key_map = {
            CONF_ENERGY_SOLAR_ENTITY: "solar_production",
            CONF_ENERGY_BATTERY_SOC_ENTITY: "battery_soc",
            CONF_ENERGY_BATTERY_POWER_ENTITY: "battery_power",
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

        # Restore billing cycle totals from DB (survives restarts)
        await self._restore_cycle_from_db(dt_util.now())

        # Restore forecast accuracy history from DB
        await self._restore_accuracy_from_db()

        # Restore peak import history for load shedding auto-learning
        await self._restore_peak_import_history()

        # Fit temperature regression from historical data
        await self._fit_temp_regression()

        # Restore EVSE state (paused, excess solar) from DB
        await self._restore_evse_state()

        # v3.13.1: Restore circuit monitor state from DB
        await self._restore_circuit_state()

        # v3.13.2: Restore MetricBaselines from DB
        await self._restore_energy_baselines()

        # Start periodic decision cycle
        self._decision_timer_unsub = async_track_time_interval(
            self.hass,
            self._async_decision_cycle,
            timedelta(minutes=self._decision_interval),
        )
        # Timer managed separately via _decision_timer_unsub — do NOT add to
        # _unsub_listeners to avoid double-unsubscribe in async_teardown

        # Run initial evaluation
        await self._async_decision_cycle()

        _LOGGER.info(
            "Energy Coordinator started (interval=%dmin, reserve=%d%%)",
            self._decision_interval,
            self._battery.reserve_soc,
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
        """Restore forecast accuracy history from DB on startup."""
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            rows = await db.get_energy_daily_recent(days=30)
            if rows:
                self._accuracy.restore_from_db(rows)
                self._predictor._adjustment_factor = (
                    self._accuracy.get_adjustment_factor()
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
        """Restore EVSE paused/excess-solar state from DB after restart."""
        db = self.hass.data.get("universal_room_automation", {}).get("database")
        if db is None:
            return
        try:
            states = await db.restore_evse_state()
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
            if states:
                _LOGGER.info(
                    "Restored EVSE state: paused=%s, excess_solar=%s",
                    list(self._ev._paused_by_us),
                    list(self._ev._excess_solar_active),
                )
        except Exception as e:
            _LOGGER.warning("Could not restore EVSE state from DB: %s", e)

    async def _save_evse_state(self) -> None:
        """Persist EVSE state to DB for restart recovery."""
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

    def _get_lifetime_consumption(self) -> float | None:
        """Read Envoy lifetime energy consumption (MWh, monotonically increasing)."""
        state = self.hass.states.get(DEFAULT_LIFETIME_CONSUMPTION_ENTITY)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_lifetime_production(self) -> float | None:
        """Read Envoy lifetime energy production (MWh, monotonically increasing)."""
        state = self.hass.states.get(DEFAULT_LIFETIME_PRODUCTION_ENTITY)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_lifetime_net_import(self) -> float | None:
        """Read Envoy lifetime net energy consumption/import (MWh, monotonically increasing)."""
        state = self.hass.states.get(DEFAULT_LIFETIME_NET_IMPORT_ENTITY)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_lifetime_net_export(self) -> float | None:
        """Read Envoy lifetime net energy production/export (MWh, monotonically increasing)."""
        state = self.hass.states.get(DEFAULT_LIFETIME_NET_EXPORT_ENTITY)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_lifetime_battery_discharged(self) -> float | None:
        """Read Envoy lifetime battery energy discharged (MWh, monotonically increasing)."""
        state = self.hass.states.get(DEFAULT_LIFETIME_BATTERY_DISCHARGED_ENTITY)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def _get_lifetime_battery_charged(self) -> float | None:
        """Read Envoy lifetime battery energy charged (MWh, monotonically increasing)."""
        state = self.hass.states.get(DEFAULT_LIFETIME_BATTERY_CHARGED_ENTITY)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

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
        else:
            self._envoy_unavailable_count += 1
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

        envoy_today_state = self.hass.states.get(DEFAULT_CONSUMPTION_TODAY_ENTITY)
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
            # Envoy reports solar_production and net_power in watts — convert to kW
            solar_prod_w = self._battery.solar_production
            net_power_w = self._battery.net_power
            solar_prod_kw = solar_prod_w / 1000.0 if solar_prod_w is not None else None
            grid_import_kw = max(net_power_w or 0, 0) / 1000.0
            solar_export_kw = abs(min(net_power_w or 0, 0)) / 1000.0

            outside_temp = None
            outside_humidity = None
            weather_state = self.hass.states.get(self._weather_entity)
            if weather_state and weather_state.attributes:
                outside_temp = weather_state.attributes.get("temperature")
                outside_humidity = weather_state.attributes.get("humidity")

            # total_consumption_kw property reads Envoy watts despite the name
            consumption_w = self.total_consumption_kw
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

            await db.log_energy_history({
                "solar_production": solar_prod_kw,
                "solar_export": solar_export_kw,
                "grid_import": grid_import_kw,
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
            weather_state = self.hass.states.get(self._weather_entity)
            outside_temp = None
            outside_humidity = None
            weather_condition = None
            if weather_state:
                weather_condition = weather_state.state
                if weather_state.attributes:
                    outside_temp = weather_state.attributes.get("temperature")
                    outside_humidity = weather_state.attributes.get("humidity")

            # Solar production is in watts from Envoy — convert to kW for DB
            solar_prod_w = self._battery.solar_production
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
                # v3.13.3: Track SOC at peak start for battery degradation detection
                if new_period == "peak":
                    soc = self._battery.battery_soc
                    if soc is not None:
                        self._soc_at_peak_baseline.update(float(soc))

            # Battery decision
            decision = self._battery.determine_mode(period, season)

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

            # Execute actions (skipped in observation mode)
            if not self._observation_mode:
                for action_spec in decision.get("actions", []):
                    await self._execute_service_action(action_spec)

                # E2: Pool optimization
                pool_actions = self._pool.determine_actions(period)
                for action_spec in pool_actions:
                    await self._execute_service_action(action_spec)

                # E2: EV charger control
                ev_actions = self._ev.determine_actions(period)
                for action_spec in ev_actions:
                    await self._execute_service_action(action_spec)

                # C2: Excess solar EVSE charging
                if self._excess_solar_enabled:
                    soc = self._battery.battery_soc
                    remaining = self._battery.solcast_remaining
                    excess_actions = self._ev.determine_excess_solar_actions(
                        soc, remaining, period,
                        soc_threshold=self._excess_solar_soc,
                        kwh_threshold=self._excess_solar_kwh,
                    )
                    for action_spec in excess_actions:
                        await self._execute_service_action(action_spec)

                # E2: Smart plug control
                plug_actions = self._smart_plugs.determine_actions(period)
                for action_spec in plug_actions:
                    await self._execute_service_action(action_spec)

            # E3: Circuit anomaly checks
            circuit_anomalies = self._circuits.check_anomalies()
            for anomaly in circuit_anomalies:
                await self._send_nm_alert(
                    title=f"Circuit Alert: {anomaly.get('circuit', 'Unknown')}",
                    message=f"Possible tripped breaker on {anomaly.get('circuit')} "
                            f"({anomaly.get('panel')} panel) — zero power for "
                            f"{anomaly.get('zero_duration_seconds', 0)}s",
                    severity="critical",
                    hazard_type="circuit_anomaly",
                    location=anomaly.get("circuit", ""),
                )

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

            # E6: HVAC constraint determination
            self._update_hvac_constraint(period)

            # E6: Energy situation assessment
            self._update_energy_situation(period)

            # Envoy availability tracking
            self._track_envoy_availability(decision)

            # Cross-check consumption tracking (hourly, when data available)
            self._crosscheck_consumption()

            # v3.11.0 D1/D2: Log energy history + external conditions every 3rd cycle (~15min)
            self._cycle_count += 1
            if self._cycle_count % 3 == 0:
                # Serialize DB writes to avoid SQLite contention
                self.hass.async_create_task(
                    self._periodic_db_writes(decision)
                )

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
        decision = self._battery.determine_mode(period, season)

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

    async def _update_forecast_temps(self) -> None:
        """Fetch daily forecast high/low via weather.get_forecasts service.

        Caches results in _cached_forecast_high/_cached_forecast_low.
        Modern HA (2024.3+) removed forecast from weather entity attributes.
        """
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
        elif tou_period == "mid_peak" and solar_class in ("poor", "very_poor"):
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
        net_power = self._battery.net_power
        if net_power is None:
            return

        # net_power is in watts, threshold is in kW — convert
        import_kw = max(net_power / 1000.0, 0.0)

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
            # Clear readings to require another sustained window for next escalation
            self._sustained_import_readings.clear()
        elif (
            not sustained
            and self._load_shedding_active_level > 0
            and len(self._sustained_import_readings) >= readings_needed
        ):
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
            _LOGGER.debug("Energy: NM alert failed (non-fatal): %s", title)

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
            pass

        avg_temp = sum(temps) / len(temps) if temps else None
        avg_humidity = sum(humids) / len(humids) if humids else None
        return avg_temp, avg_humidity

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
                            unmatched += 1
                            _LOGGER.warning(
                                "Circuit baseline '%s' has no matching circuit "
                                "(may have been renamed)", row["scope"],
                            )
                if circuit_baselines:
                    self._circuits.restore_baselines(circuit_baselines)
                if unmatched:
                    _LOGGER.warning(
                        "%d circuit baselines could not be matched", unmatched,
                    )
                _LOGGER.info(
                    "Restored %d energy baselines (peak_import: %d samples)",
                    len(rows) - unmatched,
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
        """Current EV charging status."""
        return self._ev.get_status()

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
        """Estimated time battery reaches 100%."""
        return self._predictor._battery_full_time

    @property
    def forecast_accuracy(self) -> float:
        """Rolling forecast accuracy percentage."""
        return self._accuracy.rolling_accuracy

    @property
    def predicted_import_kwh(self) -> float | None:
        """Predicted net grid import today (positive=import, negative=export)."""
        forecast = self._predictor._get_current_prediction()
        consumption = forecast.get("predicted_consumption_kwh")
        production = forecast.get("predicted_production_kwh")
        if consumption is None or production is None:
            return None
        return round(consumption - production, 1)

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

    @property
    def observation_mode(self) -> bool:
        """Whether observation mode is active (sensors only, no actions)."""
        return self._observation_mode

    @observation_mode.setter
    def observation_mode(self, value: bool) -> None:
        """Set observation mode."""
        self._observation_mode = value
        _LOGGER.info("Energy Coordinator observation mode: %s", value)

    @property
    def delivery_rate(self) -> float:
        """Current delivery + transmission rate per kWh."""
        from .energy_const import PEC_FIXED_CHARGES
        return PEC_FIXED_CHARGES["delivery_per_kwh"] + PEC_FIXED_CHARGES["transmission_per_kwh"]

    # =========================================================================
    # Monitoring accessors (consumption, EV, L1 charger)
    # =========================================================================

    def _get_state_float(self, entity_id: str) -> float | None:
        """Get numeric state from entity."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    @property
    def total_consumption_kw(self) -> float | None:
        """Total home consumption from Envoy CT (kW)."""
        from .energy_const import DEFAULT_GRID_CONSUMPTION_ENTITY
        return self._get_state_float(DEFAULT_GRID_CONSUMPTION_ENTITY)

    @property
    def net_consumption_kw(self) -> float | None:
        """Net consumption (positive=importing, negative=exporting) from Envoy (kW)."""
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
            "ev": self._ev.get_status(),
            "smart_plugs": self._smart_plugs.get_status(),
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
            "evse_battery_hold": self._evse_battery_hold_active,
        }

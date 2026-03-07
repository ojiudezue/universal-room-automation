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
    CONF_ENERGY_BATTERY_POWER_ENTITY,
    CONF_ENERGY_BATTERY_SOC_ENTITY,
    CONF_ENERGY_CHARGE_FROM_GRID_ENTITY,
    CONF_ENERGY_CONSTRAINT_COAST_OFFSET,
    CONF_ENERGY_CONSTRAINT_PRECOOL_OFFSET,
    CONF_ENERGY_CONSTRAINT_PREHEAT_OFFSET,
    CONF_ENERGY_CONSTRAINT_SHED_OFFSET,
    CONF_ENERGY_GRID_ENABLED_ENTITY,
    CONF_ENERGY_LOAD_SHEDDING_ENABLED,
    CONF_ENERGY_LOAD_SHEDDING_MODE,
    CONF_ENERGY_LOAD_SHEDDING_SUSTAINED_MINUTES,
    CONF_ENERGY_LOAD_SHEDDING_THRESHOLD,
    CONF_ENERGY_NET_POWER_ENTITY,
    CONF_ENERGY_PREHEAT_TEMP_THRESHOLD,
    CONF_ENERGY_RESERVE_SOC_ENTITY,
    CONF_ENERGY_SOLAR_ENTITY,
    CONF_ENERGY_SOLCAST_REMAINING_ENTITY,
    CONF_ENERGY_SOLCAST_TODAY_ENTITY,
    CONF_ENERGY_STORAGE_MODE_ENTITY,
    CONF_ENERGY_WEATHER_ENTITY,
    DEFAULT_CONSTRAINT_COAST_OFFSET,
    DEFAULT_CONSTRAINT_PRECOOL_OFFSET,
    DEFAULT_CONSTRAINT_PREHEAT_OFFSET,
    DEFAULT_CONSTRAINT_SHED_OFFSET,
    DEFAULT_CONSUMPTION_TODAY_ENTITY,
    DEFAULT_DECISION_INTERVAL_MINUTES,
    DEFAULT_LIFETIME_CONSUMPTION_ENTITY,
    DEFAULT_LOAD_SHEDDING_SUSTAINED_MINUTES,
    DEFAULT_LOAD_SHEDDING_THRESHOLD_KW,
    DEFAULT_PREHEAT_TEMP_THRESHOLD,
    DEFAULT_RESERVE_SOC,
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

        self._battery = BatteryStrategy(
            hass,
            reserve_soc=reserve_soc,
            entity_config=self._build_entity_map(entity_config),
            solar_classification_mode=solar_classification_mode,
            custom_solar_thresholds=custom_solar_thresholds,
        )
        # E2: Pool, EV, Smart Plugs
        self._pool = PoolOptimizer(hass, pool_speed_entity=pool_speed_entity)
        self._ev = EVChargerController(hass, evse_config=evse_config)
        self._smart_plugs = SmartPlugController(hass, plug_entities=smart_plug_entities)

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
        ec = entity_config or {}
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

        # Envoy lifetime consumption snapshot for accurate daily tracking.
        # At each date change, delta = current - snapshot = true daily consumption.
        # Uses Envoy's consumption CT (includes grid + solar self-consumed + battery).
        self._lifetime_consumption_snapshot: float | None = None

        # Envoy availability tracking
        self._envoy_unavailable_count: int = 0
        self._envoy_last_available: str | None = None
        # Cross-check: last logged divergence (avoid log spam)
        self._last_crosscheck_hour: int = -1

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

        # Fit temperature regression from historical data
        await self._fit_temp_regression()

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

    def _maybe_reset_daily(self) -> None:
        """Reset daily counters and feed accuracy tracking if date changed.

        Uses Envoy's lifetime_energy_consumption delta for true daily consumption.
        This is measured directly by the consumption CT and includes all sources
        (grid import + solar self-consumed + battery discharged to home).
        Must run BEFORE billing.accumulate() to capture yesterday's totals.
        """
        from homeassistant.util import dt as dt_util
        today = dt_util.now().date().isoformat()

        # Read current lifetime consumption for snapshot tracking
        current_lifetime = self._get_lifetime_consumption()

        if today != self._last_reset_date:
            # Capture yesterday's billing totals BEFORE they're reset
            yesterday_totals = self._billing.get_yesterday_totals()

            # Calculate yesterday's actual consumption from lifetime delta
            actual_kwh = None
            if (
                self._lifetime_consumption_snapshot is not None
                and current_lifetime is not None
                and self._last_reset_date
            ):
                # Lifetime values are in MWh — convert delta to kWh
                delta_mwh = current_lifetime - self._lifetime_consumption_snapshot
                actual_kwh = delta_mwh * 1000.0

            accuracy_result = None
            predicted_consumption = None

            if actual_kwh is not None and actual_kwh > 0:
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

            # Save daily snapshot to DB (async fire-and-forget)
            if yesterday_totals:
                error_pct = accuracy_result["pct_error"] if accuracy_result else None
                adj_factor = self._accuracy.get_adjustment_factor() if accuracy_result else None
                avg_temp = self._predictor._prediction_temperature
                self.hass.async_create_task(
                    self._save_daily_snapshot(
                        yesterday_totals,
                        actual_kwh,
                        predicted_consumption_kwh=predicted_consumption,
                        prediction_error_pct=error_pct,
                        adjustment_factor=adj_factor,
                        avg_temperature=avg_temp,
                    )
                )

            # Reset snapshot for new day
            self._lifetime_consumption_snapshot = current_lifetime
            self._tou_transition_count = 0
            self._last_reset_date = today
        elif self._lifetime_consumption_snapshot is None and current_lifetime is not None:
            # First run or Envoy was unavailable — seed the snapshot
            self._lifetime_consumption_snapshot = current_lifetime

    async def _save_daily_snapshot(
        self,
        totals: dict,
        consumption_kwh: float | None,
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
        """Cross-check our lifetime delta against Envoy's energy_consumption_today.

        Runs once per hour. If the Envoy's daily sensor and our running delta
        diverge by more than 15%, something is off (Envoy reboot, stale snapshot,
        CT calibration drift).
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
            # be stale (Envoy rebooted and lifetime reset). Re-seed it.
            if envoy_today_kwh > our_delta_kwh * 2 and our_delta_kwh < 5:
                _LOGGER.warning(
                    "Re-seeding lifetime snapshot — likely Envoy reboot detected"
                )
                self._lifetime_consumption_snapshot = current_lifetime

    async def _async_decision_cycle(self, _now=None) -> None:
        """Run the periodic decision cycle (every N minutes)."""
        if not self._enabled:
            return

        self._maybe_reset_daily()

        try:
            # Get current TOU state
            period = self._tou.get_current_period()

            # Check for period transition
            new_period = self._tou.check_period_transition()
            if new_period:
                self._tou_transition_count += 1

            # Battery decision
            decision = self._battery.determine_mode(period)
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

            # E6: Load shedding evaluation (before constraint so shed level is current)
            if not self._observation_mode:
                self._update_load_shedding(period)

            # E6: HVAC constraint determination
            self._update_hvac_constraint(period)

            # E6: Energy situation assessment
            self._update_energy_situation(period)

            # Envoy availability tracking
            self._track_envoy_availability(decision)

            # Cross-check consumption tracking (hourly, when data available)
            self._crosscheck_consumption()

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
        decision = self._battery.determine_mode(period)
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

    def _get_forecast_temps(self) -> tuple[float | None, float | None]:
        """Return (forecast_high, forecast_low) from predictor and weather entity."""
        forecast_high = None
        forecast_low = None
        if self._predictor:
            if hasattr(self._predictor, "_prediction_temperature"):
                forecast_high = self._predictor._prediction_temperature
            weather_eid = getattr(self._predictor, "_weather_entity", None)
            if weather_eid:
                ws = self.hass.states.get(weather_eid)
                if ws and ws.attributes:
                    fc = ws.attributes.get("forecast", [])
                    if fc and isinstance(fc, list) and len(fc) > 0:
                        tl = fc[0].get("templow")
                        if tl is not None:
                            try:
                                forecast_low = float(tl)
                            except (ValueError, TypeError):
                                pass
        return forecast_high, forecast_low

    def _update_hvac_constraint(self, tou_period: str) -> None:
        """Determine HVAC constraint mode based on TOU, SOC, weather, and import.

        v3.9.0-E6: Full implementation with configurable offsets, pre_heat, shed,
        max_runtime_minutes, and auto-learned load shedding threshold.
        """
        soc = self._battery.battery_soc or 0
        solar_class = self._battery.classify_solar_day()
        reason = ""
        forecast_high, forecast_low = self._get_forecast_temps()

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

        In 'auto' mode, uses the 90th percentile of historical peak import
        after 30 days. Falls back to configured fixed threshold.
        """
        if (
            self._load_shedding_mode == LOAD_SHEDDING_MODE_AUTO
            and len(self._peak_import_history) >= LOAD_SHEDDING_AUTO_MIN_DAYS * 10
        ):
            # Compute percentile from history
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

    async def async_teardown(self) -> None:
        """Tear down — cancel decision timer."""
        if self._decision_timer_unsub is not None:
            self._decision_timer_unsub()
            self._decision_timer_unsub = None
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

        forecast_high, forecast_low = self._get_forecast_temps()
        soc = self._battery.battery_soc or 0
        solar_class = self._battery.classify_solar_day()

        return {
            "mode": self._hvac_constraint_mode,
            "offset": self._hvac_constraint_offset,
            "max_runtime_minutes": max_runtime,
            "reason": self._hvac_constraint_reason,
            "solar_class": solar_class,
            "soc": soc if soc > 0 else None,
            "forecast_high_temp": forecast_high,
            "forecast_low_temp": forecast_low,
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
        }

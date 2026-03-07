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
    CONF_ENERGY_GRID_ENABLED_ENTITY,
    CONF_ENERGY_NET_POWER_ENTITY,
    CONF_ENERGY_RESERVE_SOC_ENTITY,
    CONF_ENERGY_SOLAR_ENTITY,
    CONF_ENERGY_SOLCAST_REMAINING_ENTITY,
    CONF_ENERGY_SOLCAST_TODAY_ENTITY,
    CONF_ENERGY_STORAGE_MODE_ENTITY,
    CONF_ENERGY_WEATHER_ENTITY,
    DEFAULT_DECISION_INTERVAL_MINUTES,
    DEFAULT_CONSUMPTION_TODAY_ENTITY,
    DEFAULT_LIFETIME_CONSUMPTION_ENTITY,
    DEFAULT_RESERVE_SOC,
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
    ) -> None:
        """Initialize Energy Coordinator."""
        super().__init__(
            hass,
            coordinator_id="energy",
            name="Energy Coordinator",
            priority=40,
        )
        self._decision_interval = decision_interval
        self._tou = TOURateEngine()
        self._battery = BatteryStrategy(
            hass,
            reserve_soc=reserve_soc,
            entity_config=self._build_entity_map(entity_config),
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
        self._predictor = DailyEnergyPredictor(hass)
        self._accuracy = AccuracyTracker()

        # E6: HVAC constraints + covers
        self._hvac_constraint_mode: str = "normal"
        self._hvac_constraint_offset: float = 0.0
        self._energy_situation: str = "normal"
        self._load_shedding_enabled: bool = False  # stubbed off

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

        # Cancel existing timer if re-entering (disable/enable cycle)
        if self._decision_timer_unsub is not None:
            self._decision_timer_unsub()
            self._decision_timer_unsub = None

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

            if actual_kwh is not None and actual_kwh > 0:
                self._predictor.record_actual_consumption(actual_kwh)

                # Evaluate yesterday's forecast accuracy
                forecast = self._predictor._get_current_prediction()
                predicted = forecast.get("predicted_consumption_kwh")
                accuracy_result = self._accuracy.evaluate_accuracy(
                    predicted, actual_kwh, self._last_reset_date
                )
                if accuracy_result:
                    _LOGGER.info(
                        "Forecast accuracy: predicted=%.1f actual=%.1f error=%.1f kWh (%.1f%%)",
                        predicted or 0,
                        actual_kwh,
                        accuracy_result["error_kwh"],
                        accuracy_result["pct_error"],
                    )

                # Feed Bayesian adjustment back to predictor
                self._predictor._adjustment_factor = self._accuracy.get_adjustment_factor()

            # Reset snapshot for new day
            self._lifetime_consumption_snapshot = current_lifetime
            self._tou_transition_count = 0
            self._last_reset_date = today
        elif self._lifetime_consumption_snapshot is None and current_lifetime is not None:
            # First run or Envoy was unavailable — seed the snapshot
            self._lifetime_consumption_snapshot = current_lifetime

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

    def _update_hvac_constraint(self, tou_period: str) -> None:
        """Determine HVAC constraint mode based on TOU and conditions.

        Published via dispatcher signal (stub — HVAC coordinator will consume).
        """
        soc = self._battery.battery_soc or 0
        solar_class = self._battery.classify_solar_day()

        if tou_period == "peak":
            self._hvac_constraint_mode = "coast"
            self._hvac_constraint_offset = 3.0  # Allow +3F drift
        elif tou_period == "mid_peak" and solar_class in ("poor", "very_poor"):
            self._hvac_constraint_mode = "coast"
            self._hvac_constraint_offset = 2.0
        elif tou_period == "off_peak" and soc < 50 and solar_class in ("excellent", "good"):
            # Pre-cool before peak when we have solar
            self._hvac_constraint_mode = "pre_cool"
            self._hvac_constraint_offset = -2.0
        else:
            self._hvac_constraint_mode = "normal"
            self._hvac_constraint_offset = 0.0

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
        """Current HVAC constraint for future HVAC coordinator."""
        return {
            "mode": self._hvac_constraint_mode,
            "offset": self._hvac_constraint_offset,
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

    @property
    def load_shedding_active(self) -> bool:
        """Whether any load shedding is active (pool reduced, EVs paused, plugs paused)."""
        return (
            self._pool.state != "normal"
            or bool(self._ev._paused_by_us)
            or bool(self._smart_plugs._paused_by_us)
        )

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

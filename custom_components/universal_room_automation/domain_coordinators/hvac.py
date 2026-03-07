"""HVAC Coordinator for Universal Room Automation.

Manages HVAC zones, presets, fans, covers, and energy constraint response.
Priority 30 (below Energy at 40).

v3.8.0-H1: Core + Zone Management + Preset + E6 Signal + Diagnostics Skeleton.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .base import BaseCoordinator, CoordinatorAction, Intent
from .hvac_const import (
    HVAC_ANOMALY_MIN_SAMPLES,
    HVAC_COORDINATOR_ID,
    HVAC_COORDINATOR_NAME,
    HVAC_COORDINATOR_PRIORITY,
    HVAC_METRICS,
    SIGNAL_HVAC_ENTITIES_UPDATE,
)
from .hvac_covers import CoverController
from .hvac_fans import FanController
from .hvac_override import OverrideArrester
from .hvac_preset import PresetManager
from .hvac_zones import ZoneManager
from .signals import (
    EnergyConstraint,
    SIGNAL_ENERGY_CONSTRAINT,
    SIGNAL_HOUSE_STATE_CHANGED,
)

_LOGGER = logging.getLogger(__name__)


class HVACCoordinator(BaseCoordinator):
    """HVAC Coordinator — zone comfort and cost management.

    Listens for:
    - SIGNAL_HOUSE_STATE_CHANGED → adjust presets
    - SIGNAL_ENERGY_CONSTRAINT → apply energy offsets to setpoints
    - Zone climate entity state changes → detect manual overrides
    """

    COORDINATOR_ID = HVAC_COORDINATOR_ID

    def __init__(
        self,
        hass: HomeAssistant,
        max_sleep_offset: float = 1.5,
    ) -> None:
        """Initialize HVAC Coordinator."""
        super().__init__(
            hass,
            coordinator_id=HVAC_COORDINATOR_ID,
            name=HVAC_COORDINATOR_NAME,
            priority=HVAC_COORDINATOR_PRIORITY,
        )
        self._zone_manager = ZoneManager(hass)
        self._preset_manager = PresetManager(hass, max_sleep_offset=max_sleep_offset)
        self._override_arrester = OverrideArrester(
            hass, self._zone_manager,
        )
        self._fan_controller = FanController(hass, self._zone_manager)
        self._cover_controller = CoverController(hass, self._zone_manager)

        # Energy constraint state
        self._energy_constraint: EnergyConstraint | None = None
        self._energy_constraint_mode: str = "normal"
        self._energy_offset: float = 0.0

        # House state
        self._house_state: str = ""

        # Decision cycle tracking
        self._last_evaluate: str = ""
        self._last_daily_reset: str = ""
        self._decision_timer_unsub = None
        self._pending_preset_change: bool = False

        # Diagnostics
        self._decision_logger = None
        self._compliance = None
        self._outcome = None

    @property
    def zone_manager(self) -> ZoneManager:
        """Return zone manager for sensor access."""
        return self._zone_manager

    @property
    def preset_manager(self) -> PresetManager:
        """Return preset manager for sensor access."""
        return self._preset_manager

    @property
    def override_arrester(self) -> OverrideArrester:
        """Return override arrester for sensor access."""
        return self._override_arrester

    @property
    def fan_controller(self) -> FanController:
        """Return fan controller for sensor access."""
        return self._fan_controller

    @property
    def cover_controller(self) -> CoverController:
        """Return cover controller for sensor access."""
        return self._cover_controller

    @property
    def energy_constraint_mode(self) -> str:
        """Return current energy constraint mode."""
        return self._energy_constraint_mode

    @property
    def energy_offset(self) -> float:
        """Return current energy setpoint offset."""
        return self._energy_offset

    @property
    def house_state(self) -> str:
        """Return current house state."""
        return self._house_state

    async def async_setup(self) -> None:
        """Set up HVAC Coordinator."""
        _LOGGER.info("HVAC Coordinator: starting setup")

        # Discover zones
        zone_count = await self._zone_manager.async_discover_zones()
        if zone_count == 0:
            _LOGGER.warning(
                "HVAC: No zones with thermostats found. "
                "Configure CONF_ZONE_THERMOSTAT on zone entries."
            )

        # Determine season and log
        season = self._preset_manager.determine_season()
        _LOGGER.info("HVAC: Season=%s, zones=%d", season, zone_count)

        # Subscribe to house state changes
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HOUSE_STATE_CHANGED,
                self._handle_house_state_changed,
            )
        )

        # Subscribe to energy constraints
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ENERGY_CONSTRAINT,
                self._handle_energy_constraint,
            )
        )

        # Set up diagnostics
        try:
            await self._setup_diagnostics()
        except Exception as e:
            _LOGGER.warning("HVAC: Diagnostics setup failed (non-fatal): %s", e)

        # Read initial house state from presence coordinator
        manager = self.hass.data.get("universal_room_automation", {}).get(
            "coordinator_manager"
        )
        if manager:
            presence = manager.coordinators.get("presence")
            if presence and hasattr(presence, "_house_state"):
                self._house_state = str(presence._house_state)
                _LOGGER.info("HVAC: Initial house state = %s", self._house_state)

        # Initial zone update
        self._zone_manager.update_all_zones()
        self._zone_manager.update_room_conditions()

        # Discover fans and covers
        fan_rooms = self._fan_controller.discover_fans()
        cover_count = self._cover_controller.discover_covers()
        _LOGGER.info("HVAC: %d fan rooms, %d managed covers", fan_rooms, cover_count)
        self._cover_controller.setup_listeners()

        # Start override arrester (event-driven)
        self._override_arrester.setup()

        # Start periodic decision cycle (every 5 minutes)
        self._decision_timer_unsub = async_track_time_interval(
            self.hass,
            self._async_decision_cycle,
            timedelta(minutes=5),
        )

        # Run initial cycle
        await self._async_decision_cycle()

        _LOGGER.info("HVAC Coordinator: setup complete")

    async def _setup_diagnostics(self) -> None:
        """Initialize diagnostics components."""
        from .coordinator_diagnostics import (
            AnomalyDetector,
            ComplianceTracker,
            DecisionLogger,
        )

        self._decision_logger = DecisionLogger(self.hass)
        self._compliance = ComplianceTracker(self.hass)
        self.anomaly_detector = AnomalyDetector(
            hass=self.hass,
            coordinator_id=HVAC_COORDINATOR_ID,
            metric_names=HVAC_METRICS,
            minimum_samples=HVAC_ANOMALY_MIN_SAMPLES,
        )
        try:
            await self.anomaly_detector.load_baselines()
        except Exception as e:
            _LOGGER.debug("HVAC: Could not load anomaly baselines: %s", e)

    async def _async_decision_cycle(self, _now=None) -> None:
        """Run the periodic HVAC decision cycle (every 5 minutes).

        Self-driven via async_track_time_interval — does NOT rely on the
        intent-based evaluate() path since no intents route to HVAC.
        """
        if not self._enabled:
            return

        now = dt_util.now()

        # Daily reset check
        today = now.date().isoformat()
        if today != self._last_daily_reset:
            self._last_daily_reset = today
            self._zone_manager.reset_daily_counters()
            self._preset_manager.determine_season()

        # Update zone states
        self._zone_manager.update_all_zones()
        self._zone_manager.update_room_conditions()

        # Apply presets based on house state
        await self._apply_house_state_presets()

        # Update override arrester energy state and check AC resets
        self._override_arrester.update_energy_state(
            self._energy_offset,
            self._energy_constraint_mode == "coast",
        )
        await self._override_arrester.check_ac_reset()

        # Fan and cover control
        await self._fan_controller.update(self._energy_constraint)
        await self._cover_controller.update(self._energy_constraint)

        # Record anomaly observations
        self._record_anomaly_observations()

        # Signal sensor updates
        async_dispatcher_send(self.hass, SIGNAL_HVAC_ENTITIES_UPDATE)

        self._last_evaluate = now.isoformat()

    async def evaluate(
        self,
        intents: list[Intent],
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Evaluate intents from CoordinatorManager.

        HVAC is primarily self-driven via _async_decision_cycle.
        This exists to satisfy the BaseCoordinator interface.
        """
        return []

    async def _apply_house_state_presets(self) -> None:
        """Apply preset changes based on current house state.

        Directly calls HA services (self-driven, not via CoordinatorManager actions).
        """
        if not self._house_state:
            return

        target_preset = self._preset_manager.get_preset_for_house_state(
            self._house_state
        )
        if target_preset is None:
            return

        for zone_id, zone in self._zone_manager.zones.items():
            if not self._preset_manager.should_change_preset(
                zone.preset_mode, target_preset
            ):
                continue

            # Execute the service call directly
            try:
                await self.hass.services.async_call(
                    "climate",
                    "set_preset_mode",
                    {
                        "entity_id": zone.climate_entity,
                        "preset_mode": target_preset,
                    },
                    blocking=False,
                )
                _LOGGER.info(
                    "HVAC: Set %s preset %s -> %s (house_state=%s)",
                    zone.zone_name, zone.preset_mode, target_preset,
                    self._house_state,
                )
            except Exception as e:
                _LOGGER.error(
                    "HVAC: Failed to set preset on %s: %s",
                    zone.climate_entity, e,
                )
                continue

            # Log decision
            decision_id = None
            if self._decision_logger:
                from .coordinator_diagnostics import DecisionLog

                decision_id = await self._decision_logger.log_decision(
                    DecisionLog(
                        timestamp=dt_util.utcnow(),
                        coordinator_id=self.coordinator_id,
                        decision_type="preset_change",
                        scope=f"zone:{zone_id}",
                        situation_classified=f"house_state_{self._house_state}",
                        urgency=30,
                        confidence=1.0,
                        context={
                            "house_state": self._house_state,
                            "old_preset": zone.preset_mode,
                            "new_preset": target_preset,
                        },
                        action={"preset_mode": target_preset},
                        devices_commanded=[zone.climate_entity],
                    )
                )

            # Schedule compliance check
            if self._compliance:
                await self._compliance.schedule_check(
                    decision_id=decision_id or 0,
                    scope=f"zone:{zone_id}",
                    device_type="climate",
                    device_id=zone.climate_entity,
                    commanded_state={"preset_mode": target_preset},
                )

    @callback
    def _handle_house_state_changed(self, payload: Any) -> None:
        """Handle house state change signal.

        Triggers an immediate decision cycle so presets change promptly.
        """
        if isinstance(payload, dict):
            new_state = payload.get("new_state", "")
        elif hasattr(payload, "new_state"):
            new_state = payload.new_state
        else:
            new_state = str(payload)

        old_state = self._house_state
        if new_state == old_state:
            return

        self._house_state = new_state

        _LOGGER.info(
            "HVAC: House state changed %s -> %s",
            old_state, new_state,
        )

        # Trigger immediate decision cycle
        self.hass.async_create_task(self._async_decision_cycle())

    @callback
    def _handle_energy_constraint(self, constraint: EnergyConstraint) -> None:
        """Handle energy constraint signal from Energy Coordinator."""
        old_mode = self._energy_constraint_mode

        self._energy_constraint = constraint
        self._energy_constraint_mode = constraint.mode
        self._energy_offset = constraint.setpoint_offset

        if old_mode != constraint.mode:
            _LOGGER.info(
                "HVAC: Energy constraint changed %s -> %s (offset=%.1f, fan_assist=%s)",
                old_mode,
                constraint.mode,
                constraint.setpoint_offset,
                constraint.fan_assist,
            )

    def _record_anomaly_observations(self) -> None:
        """Record observations for anomaly detection."""
        if self.anomaly_detector is None:
            return

        # Zone call frequency: count zones currently actively heating/cooling
        active_count = sum(
            1
            for z in self._zone_manager.zones.values()
            if z.hvac_action in ("cooling", "heating")
        )
        self.anomaly_detector.record_observation(
            "zone_call_frequency", "house", float(active_count)
        )

        # Override frequency (per day, logged on each cycle)
        total_overrides = sum(
            z.override_count_today for z in self._zone_manager.zones.values()
        )
        self.anomaly_detector.record_observation(
            "override_frequency", "house", float(total_overrides)
        )

    def get_anomaly_status(self) -> str:
        """Return anomaly status string for sensor."""
        if self.anomaly_detector is None:
            return "not_configured"
        learning = self.anomaly_detector.get_learning_status()
        if hasattr(learning, "value") and learning.value in (
            "insufficient_data",
            "learning",
        ):
            return learning.value
        return self.anomaly_detector.get_worst_severity().value

    def get_compliance_summary(self) -> dict[str, Any]:
        """Return compliance summary for sensor."""
        zones = self._zone_manager.zones
        return {
            "zones_total": len(zones),
            "overrides_today": sum(
                z.override_count_today for z in zones.values()
            ),
        }

    def get_mode(self) -> str:
        """Return current HVAC operating mode for sensor."""
        return self._energy_constraint_mode

    def get_mode_attrs(self) -> dict[str, Any]:
        """Return mode sensor attributes."""
        attrs: dict[str, Any] = {
            "house_state": self._house_state,
            "energy_constraint_mode": self._energy_constraint_mode,
            "energy_offset": self._energy_offset,
            "season": self._preset_manager.current_season,
            "zone_count": self._zone_manager.zone_count,
            "last_evaluate": self._last_evaluate,
        }
        if self._energy_constraint:
            attrs["fan_assist"] = self._energy_constraint.fan_assist
            attrs["occupied_only"] = self._energy_constraint.occupied_only
        fan_status = self._fan_controller.get_fan_status()
        attrs["active_fans"] = fan_status.get("active_fan_rooms", 0)
        attrs["fan_assist_active"] = fan_status.get("fan_assist_active", False)
        cover_status = self._cover_controller.get_cover_status()
        attrs["covers_closed"] = cover_status.get("covers_closed", False)
        attrs["managed_covers"] = cover_status.get("managed_covers", 0)
        return attrs

    async def async_teardown(self) -> None:
        """Tear down HVAC Coordinator."""
        _LOGGER.info("HVAC Coordinator: tearing down")

        # Cancel periodic timer
        if self._decision_timer_unsub:
            self._decision_timer_unsub()
            self._decision_timer_unsub = None

        # Tear down override arrester and cover controller
        self._override_arrester.teardown()
        self._cover_controller.teardown()

        self._cancel_listeners()

        # Save anomaly baselines
        if self.anomaly_detector:
            try:
                await self.anomaly_detector.save_baselines()
            except Exception as e:
                _LOGGER.warning("HVAC: Could not save anomaly baselines: %s", e)

        _LOGGER.info("HVAC Coordinator: teardown complete")

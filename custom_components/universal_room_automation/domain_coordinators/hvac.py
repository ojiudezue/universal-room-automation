"""HVAC Coordinator for Universal Room Automation.

Manages HVAC zones, presets, fans, covers, and energy constraint response.
Priority 30 (below Energy at 40).

v3.8.0-H1: Core + Zone Management + Preset + E6 Signal + Diagnostics Skeleton.
v3.17.0: Zone Intelligence — vacancy management, duty cycle, stale failsafe,
         person-to-zone pre-arrival, zone presence state machine.
"""

from __future__ import annotations

import asyncio
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
    CONF_HVAC_ARRESTER_ENABLED,
    DEFAULT_ARRESTER_ENABLED,
    DEFAULT_MAX_OCCUPANCY_HOURS,
    DEFAULT_VACANCY_GRACE_CONSTRAINED,
    DEFAULT_VACANCY_GRACE_MINUTES,
    DUTY_CYCLE_COAST,
    DUTY_CYCLE_SHED,
    DUTY_CYCLE_WINDOW_SECONDS,
    HVAC_ANOMALY_MIN_SAMPLES,
    HVAC_COORDINATOR_ID,
    HVAC_COORDINATOR_NAME,
    HVAC_COORDINATOR_PRIORITY,
    HVAC_METRICS,
    PRE_ARRIVAL_TIMEOUT_MINUTES,
    SIGNAL_HVAC_ENTITIES_UPDATE,
)
from .hvac_covers import CoverController
from .hvac_fans import FanController
from .hvac_override import OverrideArrester
from .hvac_predict import HVACPredictor
from .hvac_preset import PresetManager
from .hvac_zones import ZoneManager
from .signals import (
    EnergyConstraint,
    SIGNAL_ENERGY_CONSTRAINT,
    SIGNAL_HOUSE_STATE_CHANGED,
    SIGNAL_PERSON_ARRIVING,
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
        compromise_minutes: int = 30,
        ac_reset_timeout: int = 10,
        fan_activation_delta: float = 2.0,
        fan_hysteresis: float = 1.5,
        fan_min_runtime: int = 10,
        arrester_enabled: bool = DEFAULT_ARRESTER_ENABLED,
        vacancy_grace: int = DEFAULT_VACANCY_GRACE_MINUTES,
        vacancy_grace_constrained: int = DEFAULT_VACANCY_GRACE_CONSTRAINED,
        max_occupancy_hours: int = DEFAULT_MAX_OCCUPANCY_HOURS,
        person_zone_map: dict[str, list[str]] | None = None,
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
            compromise_minutes=compromise_minutes,
            ac_reset_timeout=ac_reset_timeout,
            enabled=arrester_enabled,
        )
        self._fan_controller = FanController(
            hass, self._zone_manager,
            activation_delta=fan_activation_delta,
            deactivation_delta=fan_hysteresis,
            min_runtime=fan_min_runtime,
        )
        self._cover_controller = CoverController(hass, self._zone_manager)
        self._predictor = HVACPredictor(
            hass, self._zone_manager, self._preset_manager, self._override_arrester,
        )

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

        # Observation mode — sensors run but no actions taken
        self._observation_mode: bool = False

        # Diagnostics
        self._decision_logger = None
        self._compliance = None
        self._outcome = None

        # v3.17.0: Zone Intelligence
        self._vacancy_grace = vacancy_grace
        self._vacancy_grace_constrained = vacancy_grace_constrained
        self._max_occupancy_hours = max_occupancy_hours
        self._person_zone_map: dict[str, list[str]] = person_zone_map or {}
        self._pre_arrival_zones: set[str] = set()
        self._pre_arrival_persons: dict[str, str] = {}  # zone_id -> person_entity
        self._pre_arrival_start: dict[str, Any] = {}  # zone_id -> datetime
        self._vacancy_sweeps_today: int = 0
        self._zone_intelligence_enabled: bool = True
        self._decision_cycle_lock = asyncio.Lock()
        self._pending_tasks: set[asyncio.Task] = set()
        self._last_runtime_accumulation: Any = None  # UTC datetime

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
    def predictor(self) -> HVACPredictor:
        """Return predictor for sensor access."""
        return self._predictor

    @property
    def energy_constraint_mode(self) -> str:
        """Return current energy constraint mode."""
        return self._energy_constraint_mode

    @property
    def observation_mode(self) -> bool:
        """Whether HVAC observation mode is active."""
        return self._observation_mode

    @observation_mode.setter
    def observation_mode(self, value: bool) -> None:
        """Set HVAC observation mode."""
        self._observation_mode = value
        _LOGGER.info("HVAC Coordinator observation mode: %s", value)

    @property
    def zone_intelligence_enabled(self) -> bool:
        """Whether Zone Intelligence features are active."""
        return self._zone_intelligence_enabled

    @zone_intelligence_enabled.setter
    def zone_intelligence_enabled(self, value: bool) -> None:
        """Set Zone Intelligence enabled state."""
        self._zone_intelligence_enabled = value
        _LOGGER.info("HVAC Zone Intelligence: %s", "enabled" if value else "disabled")

    @property
    def vacancy_sweeps_today(self) -> int:
        """Return count of vacancy sweeps executed today."""
        return self._vacancy_sweeps_today

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

        # v3.17.0 D3: Subscribe to person arriving signals
        self._unsub_listeners.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PERSON_ARRIVING,
                self._handle_person_arriving,
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

        # Share outdoor temp sensor with predictor
        if self._cover_controller._outdoor_temp_entity:
            self._predictor.set_outdoor_temp_entity(
                self._cover_controller._outdoor_temp_entity
            )

        # Start override arrester (event-driven)
        self._override_arrester.setup()
        self._startup_audit_done = False

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

        # Re-entrancy guard: skip if already running (e.g. signal + timer overlap)
        if self._decision_cycle_lock.locked():
            return
        async with self._decision_cycle_lock:
            await self._run_decision_cycle()

    async def _run_decision_cycle(self) -> None:
        """Inner decision cycle logic (called under lock)."""
        now = dt_util.now()

        # Daily reset check
        today = now.date().isoformat()
        if today != self._last_daily_reset:
            self._last_daily_reset = today
            # Flush predictor outcome BEFORE resetting zone counters
            # so it captures yesterday's override/reset counts
            self._predictor.flush_daily_outcome()
            self._zone_manager.reset_daily_counters()
            self._preset_manager.determine_season()
            self._vacancy_sweeps_today = 0

        # Update zone states
        self._zone_manager.update_all_zones()
        self._zone_manager.update_room_conditions()

        # One-time startup audit: catch stale overrides that survived restart
        if not self._startup_audit_done:
            self._startup_audit_done = True
            await self._override_arrester.async_startup_audit(
                self._preset_manager, self._house_state or "home_day",
            )

        now_utc = dt_util.utcnow()

        # v3.17.0: Zone Intelligence features (guarded by toggle)
        if self._zone_intelligence_enabled:
            # D5: Accumulate zone runtime BEFORE presets (RC3 ordering)
            self._accumulate_zone_runtime(now_utc)
            # D3: Clear stale pre-arrival zones
            self._expire_pre_arrival_zones(now_utc)

        if not self._observation_mode:
            # Apply presets based on house state (includes D1 vacancy + D6 failsafe)
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
        else:
            # Still update arrester state for diagnostics (no actions)
            self._override_arrester.update_energy_state(
                self._energy_offset,
                self._energy_constraint_mode == "coast",
            )

        # Predictive sensors and pre-conditioning
        zi = self._zone_intelligence_enabled
        await self._predictor.update(
            self._energy_constraint,
            self._house_state,
            pre_arrival_zones=self._pre_arrival_zones if zi else set(),
            zone_intelligence_enabled=zi,
        )

        # v3.17.0 D4: Compute zone presence states (after all other logic)
        if zi:
            self._compute_zone_presence_states(now_utc)

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

        Includes D1 vacancy override, D5 duty cycle enforcement, D6 stale failsafe.
        Directly calls HA services (self-driven, not via CoordinatorManager actions).
        """
        if not self._house_state:
            return

        target_preset = self._preset_manager.get_preset_for_house_state(
            self._house_state
        )
        if target_preset is None:
            return

        now = dt_util.utcnow()
        energy_constrained = self._energy_constraint_mode in ("coast", "shed")
        grace_minutes = (
            self._vacancy_grace_constrained if energy_constrained
            else self._vacancy_grace
        )

        zi = self._zone_intelligence_enabled
        for zone_id, zone in self._zone_manager.zones.items():
            # --- Ensure thermostat is in an active mode ---
            # Thermostats should never be left in "off" mode by URA.
            # "Away" uses relaxed setpoints via preset, not hvac_mode=off.
            # Skip zones mid-AC-reset (intentionally off for a short cycle).
            if (
                zone.hvac_mode == "off"
                and not self._override_arrester.has_active_ac_reset(zone_id)
            ):
                self._override_arrester.suppress(zone.climate_entity)
                try:
                    await self.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {
                            "entity_id": zone.climate_entity,
                            "hvac_mode": "heat_cool",
                        },
                        blocking=False,
                    )
                    _LOGGER.info(
                        "HVAC: Restored %s to heat_cool (was off)",
                        zone.zone_name,
                    )
                except Exception as e:
                    _LOGGER.error(
                        "HVAC: Failed to restore mode on %s: %s",
                        zone.climate_entity, e,
                    )

            effective_preset = target_preset
            zone_vacant_past_grace = False

            # --- D1/D5/D6: Zone Intelligence overrides (gated by toggle) ---
            if zi:
                # D1: Per-zone vacancy override
                # Only override "home" preset — sleep/away/vacation are already correct
                zone_vacant_past_grace = (
                    not zone.any_room_occupied
                    and zone.last_occupied_time is not None
                    and (now - zone.last_occupied_time).total_seconds()
                    > grace_minutes * 60
                )

                if zone_vacant_past_grace and target_preset in ("home",):
                    effective_preset = "away"

                    # Zone sweep: turn off lights + fans (once per vacancy cycle)
                    if not zone.vacancy_sweep_done and zone.vacancy_sweep_enabled:
                        await self._execute_vacancy_sweep(zone)
                        zone.vacancy_sweep_done = True
                        self._vacancy_sweeps_today += 1

                # D6: Stale occupancy failsafe (skip during sleep — RH4)
                if (
                    zone.any_room_occupied
                    and self._house_state != "sleep"
                    and zone.continuous_occupied_since is not None
                    and (now - zone.continuous_occupied_since).total_seconds()
                    > self._max_occupancy_hours * 3600
                ):
                    effective_preset = "away"
                    if not zone.vacancy_sweep_done and zone.vacancy_sweep_enabled:
                        await self._execute_vacancy_sweep(zone)
                        zone.vacancy_sweep_done = True
                        self._vacancy_sweeps_today += 1
                    _LOGGER.warning(
                        "HVAC: Zone %s occupied >%dh — treating as stale sensor",
                        zone.zone_name, self._max_occupancy_hours,
                    )

                # D5: Duty cycle enforcement (skip during sleep — RH4)
                if zone.runtime_exceeded and self._house_state != "sleep":
                    effective_preset = "away"

            # --- Determine if preset change is needed ---
            # Bypass should_change_preset() manual guard for vacancy (RH3 fix)
            if zi and (zone_vacant_past_grace or zone.runtime_exceeded) and effective_preset == "away":
                if zone.preset_mode == "away":
                    continue  # Already away
            elif not self._preset_manager.should_change_preset(
                zone.preset_mode, effective_preset
            ):
                continue

            # Suppress arrester for URA-initiated changes
            if self._override_arrester:
                self._override_arrester.suppress(zone.climate_entity)

            # Execute the service call directly
            try:
                await self.hass.services.async_call(
                    "climate",
                    "set_preset_mode",
                    {
                        "entity_id": zone.climate_entity,
                        "preset_mode": effective_preset,
                    },
                    blocking=False,
                )
                _LOGGER.info(
                    "HVAC: Set %s preset %s -> %s (house_state=%s%s)",
                    zone.zone_name, zone.preset_mode, effective_preset,
                    self._house_state,
                    " [vacancy]" if zone_vacant_past_grace and effective_preset == "away" else "",
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
                            "new_preset": effective_preset,
                            "vacancy_override": zone_vacant_past_grace,
                            "runtime_exceeded": zone.runtime_exceeded,
                        },
                        action={"preset_mode": effective_preset},
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
                    commanded_state={"preset_mode": effective_preset},
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
        task = self.hass.async_create_task(self._async_decision_cycle())
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

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
            # v3.17.0 D5: Reset duty cycle counters only when entering constrained
            # mode from normal (not on coast↔shed bounces, which would defeat enforcement)
            _MODE_RANK = {"normal": 0, "coast": 1, "shed": 2}
            if _MODE_RANK.get(old_mode, 0) == 0 and _MODE_RANK.get(constraint.mode, 0) > 0:
                for zone in self._zone_manager.zones.values():
                    zone.runtime_seconds_this_window = 0.0
                    zone.window_start = None
                    zone.runtime_exceeded = False

    # ------------------------------------------------------------------
    # v3.17.0: Zone Intelligence methods
    # ------------------------------------------------------------------

    async def _execute_vacancy_sweep(self, zone) -> None:
        """Turn off URA-configured lights and fans in all rooms of a vacant zone.

        D1: Only touches entities explicitly configured in URA room entries.
        """
        from ..const import CONF_LIGHTS, CONF_FANS, CONF_ENTRY_TYPE, CONF_ROOM_NAME, DOMAIN, ENTRY_TYPE_ROOM

        for room_name in zone.rooms:
            coordinator = self._get_room_coordinator(room_name)
            if coordinator is None:
                continue
            config = {
                **coordinator.config_entry.data,
                **coordinator.config_entry.options,
            }

            lights = config.get(CONF_LIGHTS, [])
            fans = config.get(CONF_FANS, [])

            for entity_id in lights:
                domain = entity_id.split(".")[0]
                state = self.hass.states.get(entity_id)
                if state and state.state == "on":
                    try:
                        await self.hass.services.async_call(
                            domain, "turn_off",
                            {"entity_id": entity_id}, blocking=False,
                        )
                    except Exception:  # noqa: BLE001
                        pass  # Best effort

            for entity_id in fans:
                domain = entity_id.split(".")[0]
                state = self.hass.states.get(entity_id)
                if state and state.state == "on":
                    try:
                        await self.hass.services.async_call(
                            domain, "turn_off",
                            {"entity_id": entity_id}, blocking=False,
                        )
                    except Exception:  # noqa: BLE001
                        pass

        _LOGGER.info(
            "HVAC: Vacancy sweep executed for zone %s — lights and fans off",
            zone.zone_name,
        )

    def _get_room_coordinator(self, room_name: str):
        """Get room coordinator by room name."""
        from ..const import CONF_ENTRY_TYPE, CONF_ROOM_NAME, DOMAIN, ENTRY_TYPE_ROOM

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            if entry.data.get(CONF_ROOM_NAME) == room_name:
                return self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        return None

    def _accumulate_zone_runtime(self, now: Any) -> None:
        """Track per-zone HVAC active runtime in rolling window (D5).

        Uses actual elapsed time since last call (not hardcoded 300s)
        to correctly handle ad-hoc cycles triggered by signals.
        """
        elapsed = 0.0
        if self._last_runtime_accumulation is not None:
            elapsed = min(
                (now - self._last_runtime_accumulation).total_seconds(), 300.0
            )
        self._last_runtime_accumulation = now

        for zone in self._zone_manager.zones.values():
            # Initialize window
            if zone.window_start is None:
                zone.window_start = now
                zone.runtime_seconds_this_window = 0.0
                zone.runtime_exceeded = False

            # Check window expiry → reset
            if (now - zone.window_start).total_seconds() >= DUTY_CYCLE_WINDOW_SECONDS:
                zone.window_start = now
                zone.runtime_seconds_this_window = 0.0
                zone.runtime_exceeded = False

            # Accumulate if actively heating/cooling using actual elapsed time
            if zone.hvac_action in ("heating", "cooling") and elapsed > 0:
                zone.runtime_seconds_this_window += elapsed

            # Check duty cycle
            mode = self._energy_constraint_mode
            if mode == "shed":
                max_seconds = DUTY_CYCLE_WINDOW_SECONDS * DUTY_CYCLE_SHED
            elif mode == "coast":
                max_seconds = DUTY_CYCLE_WINDOW_SECONDS * DUTY_CYCLE_COAST
            else:
                continue  # No limit in normal mode

            # Skip enforcement during sleep (RH4 fix)
            if self._house_state == "sleep":
                continue

            if zone.runtime_seconds_this_window >= max_seconds:
                zone.runtime_exceeded = True

    @callback
    def _handle_person_arriving(self, data: dict) -> None:
        """Route arriving person to preferred zones for pre-conditioning (D3)."""
        if not self._zone_intelligence_enabled:
            return
        person_entity = data.get("person_entity", "")
        preferred_zones = self._person_zone_map.get(person_entity, [])

        if not preferred_zones:
            _LOGGER.debug("HVAC: No preferred zones for %s", person_entity)
            return

        now = dt_util.utcnow()
        for zone_id in preferred_zones:
            if zone_id in self._zone_manager.zones:
                self._pre_arrival_zones.add(zone_id)
                self._pre_arrival_persons[zone_id] = person_entity
                self._pre_arrival_start[zone_id] = now

        _LOGGER.info(
            "HVAC: Pre-arrival for %s → zones %s",
            person_entity, preferred_zones,
        )

        # Trigger immediate decision cycle
        task = self.hass.async_create_task(self._async_decision_cycle())
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    def _expire_pre_arrival_zones(self, now: Any) -> None:
        """Clear stale pre-arrival zones (person didn't show up within timeout).

        When a pre-arrival zone is cleared due to timeout (not occupancy),
        turn off fans that were activated as comfort bridge.
        """
        timeout = timedelta(minutes=PRE_ARRIVAL_TIMEOUT_MINUTES)
        zones_to_defan: list = []
        for zone_id in list(self._pre_arrival_zones):
            # Clear if zone is now occupied (person arrived — fans managed by fan controller)
            zone = self._zone_manager.zones.get(zone_id)
            if zone and zone.any_room_occupied:
                self._pre_arrival_zones.discard(zone_id)
                self._pre_arrival_start.pop(zone_id, None)
                self._pre_arrival_persons.pop(zone_id, None)
                _LOGGER.info("HVAC: Pre-arrival cleared for zone %s (occupied)", zone_id)
                continue

            # Clear if timeout exceeded — also turn off pre-arrival fans
            start = self._pre_arrival_start.get(zone_id)
            if start and (now - start) > timeout:
                self._pre_arrival_zones.discard(zone_id)
                self._pre_arrival_start.pop(zone_id, None)
                self._pre_arrival_persons.pop(zone_id, None)
                if zone:
                    zones_to_defan.append(zone)
                _LOGGER.info("HVAC: Pre-arrival timeout for zone %s", zone_id)

        # Turn off fans for timed-out pre-arrival zones (best-effort)
        for zone in zones_to_defan:
            self.hass.async_create_task(self._deactivate_zone_fans(zone))

    async def _deactivate_zone_fans(self, zone) -> None:
        """Turn off fans that were activated for pre-arrival comfort bridge."""
        from ..const import CONF_FANS, CONF_ENTRY_TYPE, CONF_ROOM_NAME, DOMAIN, ENTRY_TYPE_ROOM

        for room_name in zone.rooms:
            coordinator = self._get_room_coordinator(room_name)
            if coordinator is None:
                continue
            config = {**coordinator.config_entry.data, **coordinator.config_entry.options}
            fans = config.get(CONF_FANS, [])
            for fan_entity in fans:
                domain = fan_entity.split(".")[0]
                state = self.hass.states.get(fan_entity)
                if state and state.state == "on":
                    try:
                        await self.hass.services.async_call(
                            domain, "turn_off",
                            {"entity_id": fan_entity}, blocking=False,
                        )
                    except Exception:  # noqa: BLE001
                        pass
        _LOGGER.info("HVAC: Pre-arrival fans deactivated for zone %s (timeout)", zone.zone_name)

    def _compute_zone_presence_states(self, now: Any) -> None:
        """Compute the 7-state zone presence state machine (D4).

        Priority: sleep > runtime_limited > pre_arrival > pre_conditioning
                  > occupied > vacant > away.
        """
        energy_constrained = self._energy_constraint_mode in ("coast", "shed")
        grace_minutes = (
            self._vacancy_grace_constrained if energy_constrained
            else self._vacancy_grace
        )

        pre_conditioning_zones = getattr(
            self._predictor, "_pre_conditioning_zones", set()
        )

        for zone_id, zone in self._zone_manager.zones.items():
            if self._house_state == "sleep":
                zone.zone_presence_state = "sleep"
            elif zone.runtime_exceeded:
                zone.zone_presence_state = "runtime_limited"
            elif zone_id in self._pre_arrival_zones:
                zone.zone_presence_state = "pre_arrival"
            elif zone_id in pre_conditioning_zones:
                zone.zone_presence_state = "pre_conditioning"
            elif zone.any_room_occupied:
                zone.zone_presence_state = "occupied"
            elif (
                zone.last_occupied_time is not None
                and (now - zone.last_occupied_time).total_seconds()
                <= grace_minutes * 60
            ):
                zone.zone_presence_state = "vacant"
            else:
                zone.zone_presence_state = "away"

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
        attrs["pre_cool_likelihood"] = self._predictor.pre_cool_likelihood
        attrs["comfort_risk"] = self._predictor.comfort_violation_risk
        attrs["pre_cool_active"] = self._predictor.pre_cool_active
        attrs["pre_heat_active"] = self._predictor.pre_heat_active
        attrs["observation_mode"] = self._observation_mode
        attrs["arrester_state"] = self._override_arrester.get_arrester_state()
        attrs["arrester_enabled"] = self._override_arrester.enabled
        # v3.17.0: Zone Intelligence attributes
        attrs["pre_arrival_zones"] = list(self._pre_arrival_zones)
        solar_banking_zones = getattr(
            self._predictor, "_solar_banking_zones", set()
        )
        attrs["solar_banking_zones"] = list(solar_banking_zones)
        vacancy_overrides = [
            z.zone_id for z in self._zone_manager.zones.values()
            if z.zone_presence_state == "away"
        ]
        attrs["vacancy_override_zones"] = vacancy_overrides
        attrs["person_zone_map"] = self._person_zone_map
        attrs["vacancy_sweeps_today"] = self._vacancy_sweeps_today
        return attrs

    async def async_teardown(self) -> None:
        """Tear down HVAC Coordinator."""
        _LOGGER.info("HVAC Coordinator: tearing down")

        # Cancel periodic timer
        if self._decision_timer_unsub:
            self._decision_timer_unsub()
            self._decision_timer_unsub = None

        # Cancel any in-flight ad-hoc decision cycle tasks
        for task in list(self._pending_tasks):
            task.cancel()
        self._pending_tasks.clear()

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

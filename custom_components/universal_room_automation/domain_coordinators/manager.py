"""Coordinator Manager and Conflict Resolver for domain coordinators."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Final

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from ..const import COORDINATOR_ENABLED_KEYS, DOMAIN, VERSION
from .base import (
    ActionType,
    BaseCoordinator,
    CoordinatorAction,
    Intent,
    NotificationAction,
    Severity,
    ServiceCallAction,
    SEVERITY_FACTORS,
)
from .coordinator_diagnostics import (
    AnomalyDetector,
    AnomalySeverity,
    ComplianceTracker,
    DecisionLogger,
)
from .house_state import HouseState, HouseStateMachine

_LOGGER = logging.getLogger(__name__)

# Intent batching window — collect intents for this long before processing
INTENT_BATCH_WINDOW_MS: Final = 100  # milliseconds


class ConflictResolver:
    """Resolves conflicts when multiple coordinators target the same device.

    Resolution logic:
    - Group actions by target_device
    - For each device with >1 action, pick the one with highest effective_priority
      weighted by the coordinator's base priority
    - CRITICAL severity actions always win (Safety)
    - Non-device actions (notifications, constraints, log_only) are never conflicted
    """

    def resolve(
        self,
        actions: list[tuple[BaseCoordinator, CoordinatorAction]],
    ) -> list[tuple[BaseCoordinator, CoordinatorAction]]:
        """Resolve conflicts and return the winning actions.

        Args:
            actions: List of (coordinator, action) tuples from all coordinators.

        Returns:
            List of (coordinator, action) tuples that should be executed.
        """
        if not actions:
            return []

        # Separate device-targeted actions from non-device actions
        device_actions: dict[str, list[tuple[BaseCoordinator, CoordinatorAction]]] = (
            defaultdict(list)
        )
        non_device_actions: list[tuple[BaseCoordinator, CoordinatorAction]] = []

        for coordinator, action in actions:
            if action.target_device:
                device_actions[action.target_device].append((coordinator, action))
            else:
                non_device_actions.append((coordinator, action))

        # Resolve per-device conflicts
        resolved: list[tuple[BaseCoordinator, CoordinatorAction]] = []

        for device_id, candidates in device_actions.items():
            if len(candidates) == 1:
                resolved.append(candidates[0])
                continue

            # Pick the winner: highest (coordinator.priority * action.effective_priority)
            winner = max(
                candidates,
                key=lambda ca: ca[0].priority * ca[1].effective_priority,
            )
            resolved.append(winner)

            # Log the conflict resolution
            losers = [c for c in candidates if c is not winner]
            _LOGGER.info(
                "Conflict on %s: %s (pri=%d, sev=%s) wins over %s",
                device_id,
                winner[0].coordinator_id,
                winner[0].priority,
                winner[1].severity.name,
                ", ".join(
                    f"{c.coordinator_id}(pri={c.priority},sev={a.severity.name})"
                    for c, a in losers
                ),
            )

        # Non-device actions pass through uncontested
        resolved.extend(non_device_actions)

        return resolved


class CoordinatorManager:
    """Orchestrates domain coordinators — intent queue, priority dispatch, execution.

    Lifecycle:
    1. Created during integration setup when CONF_DOMAIN_COORDINATORS_ENABLED is True.
    2. Registers coordinators (added by later cycles as they ship).
    3. Receives intents from triggers and queues them.
    4. Processes the intent queue in batches every INTENT_BATCH_WINDOW_MS.
    5. Invokes coordinators in priority order, collects actions, resolves conflicts.
    6. Executes approved actions and logs decisions.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the coordinator manager."""
        self.hass = hass
        self._coordinators: dict[str, BaseCoordinator] = {}
        self._intent_queue: list[Intent] = []
        self._conflict_resolver = ConflictResolver()
        self._house_state_machine = HouseStateMachine()
        self._processing = False
        self._batch_timer_unsub = None
        self._running = False
        self._conflicts_resolved_today: int = 0
        self._decisions_today: int = 0
        self._last_reset_date: str = ""

        # v3.6.0-c0.4: Shared diagnostics components
        self._decision_logger = DecisionLogger(hass)
        self._compliance_tracker = ComplianceTracker(hass)

        # v3.6.29: Notification Manager (not a coordinator — standalone service)
        self._notification_manager = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the Coordinator Manager device."""
        return DeviceInfo(
            identifiers={(DOMAIN, "coordinator_manager")},
            name="URA: Coordinator Manager",
            manufacturer="Universal Room Automation",
            model="Coordinator Manager",
            sw_version=VERSION,
            via_device=(DOMAIN, "integration"),
        )

    @property
    def notification_manager(self):
        """Return the Notification Manager instance."""
        return self._notification_manager

    def set_notification_manager(self, nm) -> None:
        """Set the Notification Manager instance."""
        self._notification_manager = nm
        _LOGGER.info("Notification Manager registered with Coordinator Manager")

    @property
    def house_state_machine(self) -> HouseStateMachine:
        """Return the house state machine."""
        return self._house_state_machine

    @property
    def house_state(self) -> HouseState:
        """Return the current house state."""
        return self._house_state_machine.state

    @property
    def coordinators(self) -> dict[str, BaseCoordinator]:
        """Return registered coordinators."""
        return self._coordinators

    @property
    def is_running(self) -> bool:
        """Return whether the manager is running."""
        return self._running

    @property
    def conflicts_resolved_today(self) -> int:
        """Return number of conflicts resolved today."""
        self._maybe_reset_daily_counters()
        return self._conflicts_resolved_today

    @property
    def decisions_today(self) -> int:
        """Return number of decisions made today."""
        self._maybe_reset_daily_counters()
        return self._decisions_today

    def _maybe_reset_daily_counters(self) -> None:
        """Reset daily counters if the date has changed."""
        today = dt_util.now().date().isoformat()
        if today != self._last_reset_date:
            self._conflicts_resolved_today = 0
            self._decisions_today = 0
            self._last_reset_date = today

    def register_coordinator(self, coordinator: BaseCoordinator) -> None:
        """Register a domain coordinator and inject diagnostics."""
        self._coordinators[coordinator.coordinator_id] = coordinator

        # v3.6.0-c0.4: Inject shared diagnostics components
        coordinator.decision_logger = self._decision_logger
        coordinator.compliance_tracker = self._compliance_tracker

        _LOGGER.info(
            "Registered coordinator: %s (priority=%d)",
            coordinator.coordinator_id,
            coordinator.priority,
        )

    def unregister_coordinator(self, coordinator_id: str) -> None:
        """Unregister a domain coordinator."""
        if coordinator_id in self._coordinators:
            del self._coordinators[coordinator_id]
            _LOGGER.info("Unregistered coordinator: %s", coordinator_id)

    async def async_start(self) -> None:
        """Start the coordinator manager."""
        self._running = True
        self._last_reset_date = dt_util.now().date().isoformat()

        # Set up all registered coordinators
        for coord_id, coordinator in self._coordinators.items():
            try:
                await coordinator.async_setup()
                _LOGGER.info("Coordinator %s started", coord_id)
            except Exception:
                _LOGGER.exception("Failed to start coordinator %s", coord_id)

        # v3.6.29: Start Notification Manager
        if self._notification_manager:
            try:
                await self._notification_manager.async_setup()
                self.hass.data.setdefault(DOMAIN, {})["notification_manager"] = (
                    self._notification_manager
                )
                _LOGGER.info("Notification Manager started")
            except Exception:
                _LOGGER.exception("Failed to start Notification Manager")

        _LOGGER.info(
            "Coordinator Manager started with %d coordinators",
            len(self._coordinators),
        )

    async def async_stop(self) -> None:
        """Stop the coordinator manager and tear down all coordinators."""
        self._running = False

        # Cancel pending batch timer
        if self._batch_timer_unsub is not None:
            self._batch_timer_unsub()
            self._batch_timer_unsub = None

        # Tear down all coordinators in reverse priority order
        sorted_coords = sorted(
            self._coordinators.values(),
            key=lambda c: c.priority,
        )
        for coordinator in sorted_coords:
            try:
                await coordinator.async_teardown()
                _LOGGER.info("Coordinator %s stopped", coordinator.coordinator_id)
            except Exception:
                _LOGGER.exception(
                    "Error stopping coordinator %s", coordinator.coordinator_id
                )

        # v3.6.29: Stop Notification Manager
        if self._notification_manager:
            try:
                await self._notification_manager.async_teardown()
                self.hass.data.get(DOMAIN, {}).pop("notification_manager", None)
            except Exception:
                _LOGGER.exception("Error stopping Notification Manager")

        self._intent_queue.clear()
        _LOGGER.info("Coordinator Manager stopped")

    @callback
    def queue_intent(self, intent: Intent) -> None:
        """Queue an intent for processing.

        Intents are collected in a batching window. When the first intent arrives,
        a timer is started. When the timer fires, all queued intents are processed.
        """
        if not self._running:
            return

        self._intent_queue.append(intent)

        # Start batch timer if not already running
        if self._batch_timer_unsub is None:
            self._batch_timer_unsub = async_call_later(
                self.hass,
                INTENT_BATCH_WINDOW_MS / 1000.0,
                self._async_process_batch,
            )

    async def _async_process_batch(self, _now: Any = None) -> None:
        """Process the current batch of intents."""
        self._batch_timer_unsub = None

        if self._processing or not self._intent_queue:
            return

        self._processing = True
        try:
            # Drain the queue
            intents = list(self._intent_queue)
            self._intent_queue.clear()

            # Build shared context
            context = self._build_context()

            # Collect actions from all coordinators in priority order (highest first)
            all_actions: list[tuple[BaseCoordinator, CoordinatorAction]] = []
            sorted_coords = sorted(
                self._coordinators.values(),
                key=lambda c: c.priority,
                reverse=True,
            )

            for coordinator in sorted_coords:
                if not coordinator.enabled:
                    continue

                # Filter intents for this coordinator
                coord_intents = [
                    i
                    for i in intents
                    if not i.coordinator_id
                    or i.coordinator_id == coordinator.coordinator_id
                ]
                if not coord_intents:
                    continue

                try:
                    actions = await coordinator.evaluate(coord_intents, context)
                    for action in actions:
                        all_actions.append((coordinator, action))
                except Exception:
                    _LOGGER.exception(
                        "Error evaluating coordinator %s",
                        coordinator.coordinator_id,
                    )

            if not all_actions:
                return

            # Resolve conflicts
            pre_resolve_count = len(all_actions)
            resolved = self._conflict_resolver.resolve(all_actions)
            conflicts = pre_resolve_count - len(resolved)
            if conflicts > 0:
                self._conflicts_resolved_today += conflicts

            # Execute approved actions
            for coordinator, action in resolved:
                await self._execute_action(coordinator, action)
                self._decisions_today += 1

        except Exception:
            _LOGGER.exception("Error processing intent batch")
        finally:
            self._processing = False

            # If more intents arrived during processing, schedule another batch
            if self._intent_queue and self._batch_timer_unsub is None:
                self._batch_timer_unsub = async_call_later(
                    self.hass,
                    INTENT_BATCH_WINDOW_MS / 1000.0,
                    self._async_process_batch,
                )

    def _build_context(self) -> dict[str, Any]:
        """Build the shared context dict passed to all coordinators."""
        return {
            "house_state": self._house_state_machine.state,
            "house_state_machine": self._house_state_machine.to_dict(),
            "timestamp": dt_util.utcnow().isoformat(),
            "coordinators_active": [
                c.coordinator_id
                for c in self._coordinators.values()
                if c.enabled
            ],
        }

    async def _execute_action(
        self,
        coordinator: BaseCoordinator,
        action: CoordinatorAction,
    ) -> None:
        """Execute a single approved action."""
        try:
            if action.action_type == ActionType.SERVICE_CALL:
                if isinstance(action, ServiceCallAction) and action.service:
                    domain, service = action.service.split(".", 1)
                    await self.hass.services.async_call(
                        domain,
                        service,
                        action.service_data,
                        blocking=True,
                    )
                    _LOGGER.info(
                        "Executed %s.%s on %s (coordinator=%s, severity=%s)",
                        domain,
                        service,
                        action.target_device,
                        coordinator.coordinator_id,
                        action.severity.name,
                    )

            elif action.action_type == ActionType.NOTIFICATION:
                # v3.6.29: Route NotificationAction through NM
                if isinstance(action, NotificationAction) and self._notification_manager:
                    try:
                        await self._notification_manager.async_notify(
                            coordinator_id=coordinator.coordinator_id,
                            severity=action.severity,
                            title=action.description,
                            message=action.message,
                        )
                    except Exception:
                        _LOGGER.debug("NM routing failed (non-fatal)")
                _LOGGER.info(
                    "Notification from %s: %s (severity=%s)",
                    coordinator.coordinator_id,
                    action.description,
                    action.severity.name,
                )

            elif action.action_type == ActionType.LOG_ONLY:
                _LOGGER.info(
                    "Decision logged: %s — %s (severity=%s)",
                    coordinator.coordinator_id,
                    action.description,
                    action.severity.name,
                )

            # Log decision to database
            await self._log_decision(coordinator, action)

        except Exception:
            _LOGGER.exception(
                "Error executing action from %s on %s",
                coordinator.coordinator_id,
                action.target_device,
            )

    async def _log_decision(
        self,
        coordinator: BaseCoordinator,
        action: CoordinatorAction,
    ) -> None:
        """Log a decision to the database."""
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database is None:
            return

        try:
            await database.log_coordinator_decision(
                coordinator_id=coordinator.coordinator_id,
                decision_type=action.action_type.value,
                context_json=json.dumps({"severity": action.severity.name}),
                action_json=json.dumps(
                    {
                        "target": action.target_device,
                        "description": action.description,
                        "data": str(action.data)[:500],
                    }
                ),
            )
        except Exception:
            _LOGGER.debug(
                "Failed to log decision for %s (non-fatal)",
                coordinator.coordinator_id,
            )

    def get_summary(self) -> dict[str, Any]:
        """Build coordinator summary for the summary sensor."""
        self._maybe_reset_daily_counters()

        summary: dict[str, Any] = {
            "house_state": str(self._house_state_machine.state),
            "coordinators_registered": len(self._coordinators),
            "coordinators_active": sum(
                1 for c in self._coordinators.values() if c.enabled
            ),
            "decisions_today": self._decisions_today,
            "conflicts_resolved_today": self._conflicts_resolved_today,
        }

        # Add per-coordinator status (populated by each coordinator as they ship)
        for coord_id, coordinator in self._coordinators.items():
            summary[coord_id] = f"registered (priority={coordinator.priority})"

        return summary

    def get_overall_status(self) -> str:
        """Return the overall coordinator status string."""
        if not self._running:
            return "stopped"
        if not self._coordinators:
            return "running (no coordinators)"
        return "running"

    # =========================================================================
    # v3.6.0-c0.4: Enable/Disable Coordinators
    # =========================================================================

    async def async_set_coordinator_enabled(
        self,
        coordinator_id: str,
        enabled: bool,
    ) -> bool:
        """Enable or disable a coordinator.

        When disabling: sets _enabled=False, cancels listeners, sensors show 'disabled'.
        When enabling: sets _enabled=True, calls async_setup() to re-register.
        """
        coordinator = self._coordinators.get(coordinator_id)
        if coordinator is None:
            _LOGGER.warning(
                "Cannot enable/disable unknown coordinator: %s",
                coordinator_id,
            )
            return False

        if enabled == coordinator.enabled:
            return True  # No change needed

        if enabled:
            coordinator.enabled = True
            try:
                await coordinator.async_setup()
                _LOGGER.info("Coordinator %s re-enabled", coordinator_id)
            except Exception:
                _LOGGER.exception(
                    "Error re-enabling coordinator %s", coordinator_id
                )
                coordinator.enabled = False
                return False
        else:
            coordinator.enabled = False
            coordinator._cancel_listeners()
            _LOGGER.info("Coordinator %s disabled", coordinator_id)

        return True

    def get_coordinator_status(self, coordinator_id: str) -> dict:
        """Get status for a specific coordinator."""
        coordinator = self._coordinators.get(coordinator_id)
        if coordinator is None:
            return {"status": "not_registered"}

        return {
            "status": "enabled" if coordinator.enabled else "disabled",
            "coordinator_id": coordinator_id,
            "name": coordinator.name,
            "priority": coordinator.priority,
        }

    # =========================================================================
    # v3.6.0-c0.4: Diagnostics Aggregation
    # =========================================================================

    @property
    def decision_logger(self) -> DecisionLogger:
        """Return the shared decision logger."""
        return self._decision_logger

    @property
    def compliance_tracker(self) -> ComplianceTracker:
        """Return the shared compliance tracker."""
        return self._compliance_tracker

    def get_system_anomaly_status(self) -> dict[str, Any]:
        """Get aggregated anomaly status across all coordinators."""
        self._maybe_reset_daily_counters()

        worst_severity = AnomalySeverity.NOMINAL
        total_active = 0
        total_today = 0
        worst_coordinator = ""
        worst_metric = ""
        learning_status: dict[str, str] = {}
        coordinators_with_anomalies: list[str] = []

        severity_order = {
            AnomalySeverity.NOMINAL: 0,
            AnomalySeverity.ADVISORY: 1,
            AnomalySeverity.ALERT: 2,
            AnomalySeverity.CRITICAL: 3,
        }

        for coord_id, coordinator in self._coordinators.items():
            if coordinator.anomaly_detector is None:
                learning_status[coord_id] = "not_configured"
                continue

            detector = coordinator.anomaly_detector
            status = detector.get_learning_status()
            learning_status[coord_id] = status

            summary = detector.get_status_summary()
            active = summary.get("active_anomalies", 0)
            today = summary.get("anomalies_today", 0)
            total_active += active
            total_today += today

            if active > 0:
                coordinators_with_anomalies.append(coord_id)

            coord_severity = detector.get_worst_severity()
            if severity_order.get(coord_severity, 0) > severity_order.get(
                worst_severity, 0
            ):
                worst_severity = coord_severity
                worst_coordinator = coord_id
                metric_name, _z = detector.get_worst_metric()
                worst_metric = metric_name

        return {
            "state": worst_severity.value,
            "active_anomalies": total_active,
            "anomalies_today": total_today,
            "worst_severity": worst_severity.value,
            "worst_coordinator": worst_coordinator,
            "worst_metric": worst_metric,
            "coordinators_with_anomalies": coordinators_with_anomalies,
            "learning_status": learning_status,
        }

    def get_diagnostics_summary(self) -> dict[str, Any]:
        """Get full diagnostics summary across all coordinators."""
        summary: dict[str, Any] = {
            "system_anomaly": self.get_system_anomaly_status(),
            "coordinators": {},
        }

        for coord_id, coordinator in self._coordinators.items():
            summary["coordinators"][coord_id] = (
                coordinator.get_diagnostics_summary()
            )

        return summary

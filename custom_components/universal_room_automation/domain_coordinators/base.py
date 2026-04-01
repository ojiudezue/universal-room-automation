"""Base coordinator and shared models for domain coordinators."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass
from typing import TYPE_CHECKING, Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from ..const import DOMAIN, VERSION, CONF_ENTRY_TYPE, ENTRY_TYPE_COORDINATOR_MANAGER

if TYPE_CHECKING:
    from .coordinator_diagnostics import (
        AnomalyDetector,
        ComplianceTracker,
        DecisionLogger,
    )

_LOGGER = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class Severity(IntEnum):
    """Action severity levels.

    Higher values = more urgent. Used in conflict resolution scoring:
    effective_priority = base_priority * severity_factor * confidence_factor
    """

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class ActionType(StrEnum):
    """Types of coordinator actions."""

    SERVICE_CALL = "service_call"
    NOTIFICATION = "notification"
    CONSTRAINT = "constraint"
    LOG_ONLY = "log_only"


# Severity multipliers for conflict resolution
SEVERITY_FACTORS: Final[dict[Severity, float]] = {
    Severity.LOW: 0.5,
    Severity.MEDIUM: 1.0,
    Severity.HIGH: 2.0,
    Severity.CRITICAL: 10.0,  # CRITICAL effectively wins all conflicts
}


# ============================================================================
# Data classes
# ============================================================================


@dataclass
class Intent:
    """A trigger event queued for coordinator processing.

    Intents represent "something happened" — a state change, time event,
    census update, etc. The CoordinatorManager collects intents in a
    batching window and dispatches them to coordinators in priority order.
    """

    source: str  # e.g., "state_change", "time_trigger", "census_update"
    entity_id: str = ""  # triggering entity (if any)
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: dt_util.utcnow().isoformat())
    coordinator_id: str = ""  # target coordinator (empty = broadcast)


@dataclass
class CoordinatorAction:
    """A proposed action from a coordinator.

    After evaluate(), coordinators return a list of these. The ConflictResolver
    groups them by target_device and picks the winner per device.

    All fields have defaults so that dataclass inheritance works on Python 3.9+.
    """

    coordinator_id: str = ""
    action_type: ActionType = ActionType.LOG_ONLY
    target_device: str = ""  # entity_id of the target device (or "" for non-device actions)
    severity: Severity = Severity.LOW
    confidence: float = 1.0  # 0.0 - 1.0
    description: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_priority(self) -> float:
        """Compute effective priority for conflict resolution.

        effective_priority = base_priority * severity_factor * confidence
        base_priority is set by the coordinator's priority attribute.
        """
        return SEVERITY_FACTORS.get(self.severity, 1.0) * self.confidence


@dataclass
class ServiceCallAction(CoordinatorAction):
    """An action that calls a Home Assistant service."""

    action_type: ActionType = ActionType.SERVICE_CALL
    service: str = ""  # e.g., "light.turn_on"
    service_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationAction(CoordinatorAction):
    """An action that sends a notification."""

    action_type: ActionType = ActionType.NOTIFICATION
    message: str = ""
    channels: list[str] = field(default_factory=list)
    hazard_type: str = ""  # Maps to NM light pattern (e.g., "intruder", "fire")
    location: str = ""  # Source entity/room for context


@dataclass
class ConstraintAction(CoordinatorAction):
    """An action that publishes a constraint for another coordinator."""

    action_type: ActionType = ActionType.CONSTRAINT
    constraint_type: str = ""  # e.g., "hvac_setback", "fan_assist"
    constraint_data: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Base Coordinator
# ============================================================================


class BaseCoordinator(ABC):
    """Abstract base class for all domain coordinators.

    Subclasses must implement:
    - async_setup(): Initialize the coordinator (subscribe to triggers, etc.)
    - evaluate(intents, context): Process intents and return proposed actions
    - async_teardown(): Clean up on shutdown

    Properties:
    - coordinator_id: unique string identifier (e.g., "presence", "safety")
    - priority: integer priority (higher = more important, Safety=100, Comfort=20)
    - name: human-readable name
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator_id: str,
        name: str,
        priority: int,
    ) -> None:
        """Initialize the base coordinator."""
        self.hass = hass
        self.coordinator_id = coordinator_id
        self.name = name
        self.priority = priority
        self._enabled = True
        self._unsub_listeners: list = []

        # v3.6.0-c0.4: Diagnostics — injected by CoordinatorManager
        self.decision_logger: DecisionLogger | None = None
        self.compliance_tracker: ComplianceTracker | None = None
        self.anomaly_detector: AnomalyDetector | None = None

    @property
    def enabled(self) -> bool:
        """Return whether the coordinator is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Set the enabled state."""
        self._enabled = value

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this coordinator's device."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.coordinator_id}_coordinator")},
            name=f"URA: {self.name}",
            manufacturer="Universal Room Automation",
            model="Domain Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @abstractmethod
    async def async_setup(self) -> None:
        """Set up the coordinator — register listeners, load config, etc."""

    @abstractmethod
    async def evaluate(
        self,
        intents: list[Intent],
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Evaluate intents and return proposed actions.

        Args:
            intents: List of Intent objects targeted at this coordinator.
            context: Shared context dict containing house_state, census data, etc.

        Returns:
            List of CoordinatorAction objects to be resolved and executed.
        """

    @abstractmethod
    async def async_teardown(self) -> None:
        """Tear down the coordinator — unsubscribe listeners, clean up."""

    def is_hazard_active(self, hazard_type: str, location: str) -> bool:
        """Check if a specific hazard is still active. Override in subclasses."""
        return False

    def get_diagnostics_summary(self) -> dict[str, Any]:
        """Return diagnostics summary for this coordinator.

        Includes anomaly status, learning status, and compliance info
        when diagnostics components are injected.
        """
        summary: dict[str, Any] = {
            "coordinator_id": self.coordinator_id,
            "enabled": self._enabled,
            "priority": self.priority,
        }

        if self.anomaly_detector is not None:
            anomaly_summary = self.anomaly_detector.get_status_summary()
            summary["anomaly"] = {
                "learning_status": anomaly_summary.get("learning_status", "unknown"),
                "active_anomalies": anomaly_summary.get("active_anomalies", 0),
                "anomalies_today": anomaly_summary.get("anomalies_today", 0),
                "worst_severity": self.anomaly_detector.get_worst_severity().value,
                "metrics": anomaly_summary.get("metrics", {}),
            }
        else:
            summary["anomaly"] = {"learning_status": "not_configured"}

        return summary

    def _get_signal_config(self, key: str, default: bool = False) -> bool:
        """Read a signal response config from the Coordinator Manager entry.

        v3.22.0: Cross-coordinator signal response toggles are stored in the
        CM entry options. All default to False (OFF) so no cross-coordinator
        behavior fires unless explicitly enabled by the user.
        """
        cm_entry = None
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                cm_entry = entry
                break
        if cm_entry is None:
            return default
        config = {**cm_entry.data, **cm_entry.options}
        return config.get(key, default)

    def _cancel_listeners(self) -> None:
        """Cancel all registered state listeners."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

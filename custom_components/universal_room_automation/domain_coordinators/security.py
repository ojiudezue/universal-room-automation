"""Security Coordinator — armed state, entry monitoring, lock control, camera triggers.

Manages armed states, entry sensor monitoring, lock control, security camera
recording triggers, and periodic lock compliance checks. Second active-control
coordinator after Safety (priority 80).

v3.6.0-c3: Initial implementation.

Key design decisions:
  - All locks, lights, cameras manually configured — no auto-discovery (req #1, #5)
  - Camera recording disabled by default (req #2)
  - Coordinator can be disabled entirely (req #3)
  - Armed state flag, optionally coupled to alarm panel (req #4)
  - Auto-follow house state off by default (req #6)
  - Unknown person detection → lock all doors (req #7)
  - Periodic lock check at configurable interval, armed-independent (req #8)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_SECURITY_ALARM_PANEL,
    CONF_SECURITY_AUTO_FOLLOW,
    CONF_SECURITY_CAMERA_ENTITIES,
    CONF_SECURITY_CAMERA_RECORD_DURATION,
    CONF_SECURITY_CAMERA_RECORDING,
    CONF_SECURITY_ENTRY_SENSORS,
    CONF_SECURITY_GARAGE_ENTITIES,
    CONF_SECURITY_LIGHT_ENTITIES,
    CONF_SECURITY_LOCK_CHECK_INTERVAL,
    CONF_SECURITY_LOCK_ENTITIES,
    DOMAIN,
)
from .base import (
    BaseCoordinator,
    CoordinatorAction,
    Intent,
    NotificationAction,
    ServiceCallAction,
    Severity,
)
from .signals import SIGNAL_SECURITY_ENTITIES_UPDATE

_LOGGER = logging.getLogger(__name__)

# Metrics tracked by anomaly detection
SECURITY_METRICS = ["alert_trigger_frequency", "entry_anomaly_score"]


# ============================================================================
# Enums
# ============================================================================


class ArmedState(StrEnum):
    DISARMED = "disarmed"
    ARMED_HOME = "armed_home"
    ARMED_AWAY = "armed_away"
    ARMED_VACATION = "armed_vacation"


class EntryVerdict(StrEnum):
    SANCTIONED = "sanctioned"
    NOTIFY = "notify"
    LOG_ONLY = "log_only"
    INVESTIGATE = "investigate"
    ALERT = "alert"
    ALERT_HIGH = "alert_high"


# Map HA alarm panel states to ArmedState
_ALARM_STATE_MAP: dict[str, ArmedState] = {
    "disarmed": ArmedState.DISARMED,
    "armed_home": ArmedState.ARMED_HOME,
    "armed_away": ArmedState.ARMED_AWAY,
    "armed_vacation": ArmedState.ARMED_VACATION,
    "armed_night": ArmedState.ARMED_HOME,
    "armed_custom_bypass": ArmedState.ARMED_HOME,
}

# Map ArmedState to alarm panel service
_ARMED_TO_ALARM_SERVICE: dict[ArmedState, str] = {
    ArmedState.DISARMED: "alarm_disarm",
    ArmedState.ARMED_HOME: "alarm_arm_home",
    ArmedState.ARMED_AWAY: "alarm_arm_away",
    ArmedState.ARMED_VACATION: "alarm_arm_vacation",
}

# Verdict → severity mapping
_VERDICT_SEVERITY: dict[EntryVerdict, Severity] = {
    EntryVerdict.SANCTIONED: Severity.LOW,
    EntryVerdict.LOG_ONLY: Severity.LOW,
    EntryVerdict.NOTIFY: Severity.LOW,
    EntryVerdict.INVESTIGATE: Severity.MEDIUM,
    EntryVerdict.ALERT: Severity.HIGH,
    EntryVerdict.ALERT_HIGH: Severity.CRITICAL,
}


# ============================================================================
# Helper classes
# ============================================================================


@dataclass
class EntryEvent:
    """Represents a door/window open event."""

    entity_id: str
    timestamp: datetime = field(default_factory=dt_util.utcnow)
    new_state: str = "on"
    old_state: str = "off"


class SanctionChecker:
    """Checks census/person data to classify entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._expected_arrivals: dict[str, datetime] = {}
        self._authorized_guests: dict[str, datetime] = {}

    def add_expected_arrival(self, person_id: str, window_minutes: int = 30) -> None:
        """Add a person to the expected arrivals list."""
        self._expected_arrivals[person_id] = dt_util.utcnow() + timedelta(
            minutes=window_minutes
        )

    def authorize_guest(self, person_name: str, expires_hours: float = 24) -> None:
        """Add an authorized guest."""
        self._authorized_guests[person_name] = dt_util.utcnow() + timedelta(
            hours=expires_hours
        )

    def check_entry(self, context: dict[str, Any]) -> EntryVerdict:
        """Evaluate an entry event against census data."""
        now = dt_util.utcnow()

        # Clean expired entries
        self._expected_arrivals = {
            k: v for k, v in self._expected_arrivals.items() if v > now
        }
        self._authorized_guests = {
            k: v for k, v in self._authorized_guests.items() if v > now
        }

        census = context.get("census", {})

        # Validate census freshness — stale data (>5 min) should not be trusted
        census_ts = census.get("timestamp")
        if census_ts:
            try:
                ts = datetime.fromisoformat(census_ts) if isinstance(census_ts, str) else census_ts
                age = (now - ts).total_seconds()
                if age > 300:  # 5 minutes
                    _LOGGER.warning("Census data stale (%.0fs old), treating as uncertain", age)
                    return EntryVerdict.INVESTIGATE
            except (ValueError, TypeError):
                pass
        persons_home = census.get("persons_home", [])
        unknown_present = census.get("unknown_present", False)

        # Unknown person → highest alert
        if unknown_present:
            return EntryVerdict.ALERT_HIGH

        # Check expected arrivals
        if self._expected_arrivals:
            return EntryVerdict.SANCTIONED

        # Check authorized guests
        if self._authorized_guests:
            return EntryVerdict.SANCTIONED

        # Known persons home → sanctioned
        if persons_home:
            return EntryVerdict.SANCTIONED

        # Nobody home and door opens → investigate
        return EntryVerdict.INVESTIGATE

    def has_unknown_persons(self, context: dict[str, Any]) -> bool:
        """Check if unknown persons are detected."""
        census = context.get("census", {})
        return census.get("unknown_present", False)


class EntryProcessor:
    """Evaluates door/window events against armed state and census."""

    def __init__(
        self,
        hass: HomeAssistant,
        sanction_checker: SanctionChecker,
    ) -> None:
        self.hass = hass
        self._sanction_checker = sanction_checker

    def evaluate_entry(
        self,
        event: EntryEvent,
        armed_state: ArmedState,
        context: dict[str, Any],
    ) -> EntryVerdict:
        """Evaluate an entry event and return a verdict."""
        if armed_state == ArmedState.DISARMED:
            # Even when disarmed, unknown persons trigger alert
            if self._sanction_checker.has_unknown_persons(context):
                return EntryVerdict.ALERT_HIGH
            return EntryVerdict.LOG_ONLY

        # Armed — run full sanction check
        verdict = self._sanction_checker.check_entry(context)

        # Escalate based on armed level
        if armed_state in (ArmedState.ARMED_AWAY, ArmedState.ARMED_VACATION):
            if verdict == EntryVerdict.INVESTIGATE:
                verdict = EntryVerdict.ALERT
            elif verdict == EntryVerdict.NOTIFY:
                verdict = EntryVerdict.INVESTIGATE

        return verdict


class CameraRecordDispatcher:
    """Dispatches recording triggers to cameras based on detected platform."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._camera_platforms: dict[str, str] = {}

    async def async_setup(self, camera_entities: list[str]) -> None:
        """Detect camera platforms from entity registry."""
        try:
            from homeassistant.helpers import entity_registry as er

            registry = er.async_get(self.hass)
            for entity_id in camera_entities:
                entry = registry.async_get(entity_id)
                if entry is not None:
                    platform = entry.platform or "generic"
                    self._camera_platforms[entity_id] = platform
                    _LOGGER.debug(
                        "Camera %s detected as platform: %s", entity_id, platform
                    )
                else:
                    self._camera_platforms[entity_id] = "generic"
        except Exception:
            _LOGGER.warning("Failed to detect camera platforms, using generic")
            for entity_id in camera_entities:
                self._camera_platforms[entity_id] = "generic"

    def _build_camera_actions(
        self,
        camera_entities: list[str],
        duration: int = 30,
    ) -> list[ServiceCallAction]:
        """Generate platform-aware service call actions for camera recording."""
        actions: list[ServiceCallAction] = []
        for entity_id in camera_entities:
            platform = self._camera_platforms.get(entity_id, "generic")
            action = self._build_record_action(entity_id, platform, duration)
            if action:
                actions.append(action)
        return actions

    def _build_record_action(
        self,
        entity_id: str,
        platform: str,
        duration: int,
    ) -> ServiceCallAction | None:
        """Build platform-specific recording action."""
        if platform == "frigate":
            return ServiceCallAction(
                coordinator_id="security",
                target_device=entity_id,
                severity=Severity.HIGH,
                service="frigate.record",
                service_data={"entity_id": entity_id, "duration": duration},
                description=f"Frigate record trigger on {entity_id}",
            )
        elif platform == "unifiprotect":
            return ServiceCallAction(
                coordinator_id="security",
                target_device=entity_id,
                severity=Severity.HIGH,
                service="unifiprotect.set_recording_mode",
                service_data={"entity_id": entity_id, "recording_mode": "always"},
                description=f"UniFi Protect record trigger on {entity_id}",
            )
        elif platform == "reolink":
            return ServiceCallAction(
                coordinator_id="security",
                target_device=entity_id,
                severity=Severity.HIGH,
                service="camera.record",
                service_data={
                    "entity_id": entity_id,
                    "duration": duration,
                },
                description=f"Reolink record trigger on {entity_id}",
            )
        else:
            # Generic HA camera.record
            return ServiceCallAction(
                coordinator_id="security",
                target_device=entity_id,
                severity=Severity.HIGH,
                service="camera.record",
                service_data={
                    "entity_id": entity_id,
                    "duration": duration,
                },
                description=f"Camera record trigger on {entity_id}",
            )


class SecurityPatternLearner:
    """Learns normal entry patterns per entry point using MetricBaseline."""

    MINIMUM_DAYS = 30

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._entry_history: dict[str, list[datetime]] = defaultdict(list)
        self._start_time: datetime = dt_util.utcnow()

    @property
    def learning_active(self) -> bool:
        """Return True if enough data has been collected."""
        elapsed = dt_util.utcnow() - self._start_time
        return elapsed.days >= self.MINIMUM_DAYS

    def record_entry(self, entity_id: str) -> None:
        """Record an entry event for pattern learning."""
        self._entry_history[entity_id].append(dt_util.utcnow())
        # Keep last 90 days
        cutoff = dt_util.utcnow() - timedelta(days=90)
        self._entry_history[entity_id] = [
            ts for ts in self._entry_history[entity_id] if ts > cutoff
        ]

    def is_anomalous(self, entity_id: str) -> bool:
        """Check if a current entry is anomalous based on historical patterns."""
        if not self.learning_active:
            return False

        history = self._entry_history.get(entity_id, [])
        if len(history) < 10:
            return False

        now = dt_util.utcnow()
        current_hour = now.hour

        # Count entries at this hour historically
        hour_counts: dict[int, int] = defaultdict(int)
        for ts in history:
            hour_counts[ts.hour] += 1

        total = sum(hour_counts.values())
        if total == 0:
            return False

        hour_ratio = hour_counts.get(current_hour, 0) / total
        # If less than 2% of entries happen at this hour, it's anomalous
        return hour_ratio < 0.02


# ============================================================================
# Main Coordinator
# ============================================================================


class SecurityCoordinator(BaseCoordinator):
    """Security Coordinator — armed state, entry monitoring, lock control.

    Priority 80: below Safety (100), above Energy/HVAC/Comfort.
    """

    COORDINATOR_ID = "security"
    PRIORITY = 80

    def __init__(
        self,
        hass: HomeAssistant,
        lock_entities: list[str] | None = None,
        garage_entities: list[str] | None = None,
        entry_sensors: list[str] | None = None,
        security_lights: list[str] | None = None,
        camera_entities: list[str] | None = None,
        camera_recording_enabled: bool = False,
        camera_record_duration: int = 30,
        alarm_panel_entity: str | None = None,
        auto_follow_house_state: bool = False,
        lock_check_interval: int = 30,
    ) -> None:
        """Initialize the Security Coordinator."""
        super().__init__(
            hass,
            coordinator_id=self.COORDINATOR_ID,
            name="Security Coordinator",
            priority=self.PRIORITY,
        )
        self._armed_state = ArmedState.DISARMED
        self._lock_entities = lock_entities or []
        self._garage_entities = garage_entities or []
        self._entry_sensors = entry_sensors or []
        self._security_light_entities = security_lights or []
        self._camera_entities = camera_entities or []
        self._camera_recording_enabled = camera_recording_enabled
        self._camera_record_duration = camera_record_duration
        self._alarm_panel_entity = alarm_panel_entity
        self._auto_follow_house_state = auto_follow_house_state
        self._lock_check_interval = lock_check_interval

        # Runtime state
        self._active_alert = False
        self._alert_details: dict[str, Any] = {}
        self._last_entry_event: dict[str, Any] = {}
        self._lock_compliance: dict[str, str] = {}  # entity_id -> "locked"/"unlocked"
        self._alerts_today: int = 0
        self._lock_checks_today: int = 0
        self._last_reset_date: str = ""

        # Sub-components
        self._sanction_checker = SanctionChecker(hass)
        self._entry_processor = EntryProcessor(hass, self._sanction_checker)
        self._camera_dispatcher = CameraRecordDispatcher(hass)
        self._pattern_learner = SecurityPatternLearner(hass)

        # Sync guard to prevent bidirectional alarm panel loops
        self._syncing_alarm_panel = False

        # Entry sensor debounce: entity_id -> last trigger timestamp
        self._entry_debounce: dict[str, datetime] = {}
        self._entry_debounce_seconds: int = 10

    async def async_setup(self) -> None:
        """Set up the Security Coordinator."""
        _LOGGER.info(
            "Setting up Security Coordinator: %d locks, %d garage doors, "
            "%d entry sensors, %d lights, %d cameras, alarm_panel=%s, "
            "auto_follow=%s, camera_recording=%s, lock_check=%dm",
            len(self._lock_entities),
            len(self._garage_entities),
            len(self._entry_sensors),
            len(self._security_light_entities),
            len(self._camera_entities),
            self._alarm_panel_entity or "none",
            self._auto_follow_house_state,
            self._camera_recording_enabled,
            self._lock_check_interval,
        )

        # Entry sensor state listeners
        if self._entry_sensors:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self.hass,
                    self._entry_sensors,
                    self._handle_entry_sensor_change,
                )
            )

        # Alarm panel bidirectional sync
        if self._alarm_panel_entity:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self.hass,
                    [self._alarm_panel_entity],
                    self._handle_alarm_panel_change,
                )
            )

        # Periodic lock check
        if self._lock_check_interval > 0 and (
            self._lock_entities or self._garage_entities
        ):
            self._unsub_listeners.append(
                async_track_time_interval(
                    self.hass,
                    self._handle_periodic_lock_check,
                    timedelta(minutes=self._lock_check_interval),
                )
            )

        # Camera platform detection
        if self._camera_recording_enabled and self._camera_entities:
            await self._camera_dispatcher.async_setup(self._camera_entities)

        # Anomaly detection setup
        from .coordinator_diagnostics import AnomalyDetector

        self.anomaly_detector = AnomalyDetector(
            self.hass, self.COORDINATOR_ID, SECURITY_METRICS
        )
        try:
            await self.anomaly_detector.load_baselines()
        except Exception:
            _LOGGER.debug("Failed to load security anomaly baselines (non-fatal)")

        _LOGGER.info("Security Coordinator setup complete")

    async def evaluate(
        self,
        intents: list[Intent],
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Evaluate intents and return proposed actions."""
        actions: list[CoordinatorAction] = []
        self._maybe_reset_daily_counters()

        for intent in intents:
            if intent.source == "state_change" and intent.entity_id in self._entry_sensors:
                actions.extend(self._handle_entry_intent(intent, context))
            elif intent.source == "census_update":
                actions.extend(self._handle_census_intent(intent, context))
            elif intent.source == "house_state_change" and self._auto_follow_house_state:
                actions.extend(self._handle_house_state_intent(intent))
            elif intent.source == "alarm_panel_change":
                self._handle_alarm_sync(intent)
            elif intent.source == "periodic_lock_check":
                actions.extend(await self._evaluate_lock_check())

        return actions

    async def async_teardown(self) -> None:
        """Tear down the Security Coordinator."""
        self._cancel_listeners()
        if self.anomaly_detector is not None:
            try:
                await self.anomaly_detector.save_baselines()
            except Exception:
                _LOGGER.debug("Failed to save security anomaly baselines (non-fatal)")
        _LOGGER.info("Security Coordinator torn down")

    # =========================================================================
    # Intent handlers
    # =========================================================================

    def _handle_entry_intent(
        self,
        intent: Intent,
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Handle an entry sensor state change intent."""
        event = EntryEvent(
            entity_id=intent.entity_id,
            new_state=intent.data.get("new_state", "on"),
            old_state=intent.data.get("old_state", "off"),
        )

        # Only process door/window opening (off→on or closed→open)
        if event.new_state not in ("on", "open"):
            return []

        # Debounce: skip if same sensor fired within cooldown window
        now = dt_util.utcnow()
        last_trigger = self._entry_debounce.get(intent.entity_id)
        if last_trigger and (now - last_trigger).total_seconds() < self._entry_debounce_seconds:
            _LOGGER.debug("Entry debounced: %s (%.1fs since last)", intent.entity_id,
                          (now - last_trigger).total_seconds())
            return []
        self._entry_debounce[intent.entity_id] = now

        # Record for pattern learning
        self._pattern_learner.record_entry(intent.entity_id)

        verdict = self._entry_processor.evaluate_entry(
            event, self._armed_state, context
        )

        # Update last entry event
        self._last_entry_event = {
            "entity_id": intent.entity_id,
            "verdict": verdict.value,
            "armed_state": self._armed_state.value,
            "timestamp": dt_util.utcnow().isoformat(),
        }

        # Record anomaly observation
        if self.anomaly_detector is not None:
            severity_score = _VERDICT_SEVERITY.get(verdict, Severity.LOW).value
            self.anomaly_detector.record_observation(
                "alert_trigger_frequency", "house", float(severity_score)
            )

        actions = self._verdict_to_actions(verdict, intent.entity_id)

        # Fire entity update signal
        async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)

        return actions

    def _handle_census_intent(
        self,
        intent: Intent,
        context: dict[str, Any],
    ) -> list[CoordinatorAction]:
        """Handle census update — check for unknown persons (req #7)."""
        if not self._sanction_checker.has_unknown_persons(context):
            return []

        _LOGGER.warning("Unknown person detected — locking all doors")
        self._active_alert = True
        self._alert_details = {
            "type": "unknown_person",
            "timestamp": dt_util.utcnow().isoformat(),
        }
        self._alerts_today += 1

        actions = self._generate_lockdown_actions("Unknown person detected on property")

        # Camera trigger if enabled (uses platform-aware dispatcher)
        if self._camera_recording_enabled and self._camera_entities:
            actions.extend(
                self._camera_dispatcher._build_camera_actions(
                    self._camera_entities, self._camera_record_duration
                )
            )

        # Notification
        actions.append(
            NotificationAction(
                coordinator_id=self.COORDINATOR_ID,
                severity=Severity.HIGH,
                message="Unknown person detected — all doors locked",
                channels=["security"],
                description="Unknown person alert notification",
            )
        )

        async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)
        return actions

    def _handle_house_state_intent(
        self,
        intent: Intent,
    ) -> list[CoordinatorAction]:
        """Handle house state change when auto-follow is enabled (req #6)."""
        new_house_state = intent.data.get("new_state", "")

        state_mapping = {
            "away": ArmedState.ARMED_AWAY,
            "home_day": ArmedState.ARMED_HOME,
            "home_evening": ArmedState.ARMED_HOME,
            "home_night": ArmedState.ARMED_HOME,
            "sleep": ArmedState.ARMED_HOME,
            "vacation": ArmedState.ARMED_VACATION,
            "arriving": ArmedState.DISARMED,
            "waking": ArmedState.DISARMED,
            "guest": ArmedState.ARMED_HOME,
        }

        new_armed = state_mapping.get(new_house_state)
        if new_armed is None or new_armed == self._armed_state:
            return []

        old_state = self._armed_state
        self._armed_state = new_armed
        _LOGGER.info(
            "Auto-follow: house state %s → armed state %s (was %s)",
            new_house_state,
            new_armed.value,
            old_state.value,
        )

        # Log decision
        if self.decision_logger is not None:
            from .coordinator_diagnostics import DecisionLog

            self.decision_logger.log_decision(
                DecisionLog(
                    coordinator_id=self.COORDINATOR_ID,
                    decision_type="armed_state_change",
                    context=f"auto_follow: {new_house_state}",
                    action=f"{old_state.value} → {new_armed.value}",
                )
            )

        # Always signal sensor update since armed state changed
        async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)

        # Sync to alarm panel if coupled
        if self._alarm_panel_entity:
            service = _ARMED_TO_ALARM_SERVICE.get(new_armed)
            if service:
                return [
                    ServiceCallAction(
                        coordinator_id=self.COORDINATOR_ID,
                        target_device=self._alarm_panel_entity,
                        severity=Severity.MEDIUM,
                        service=f"alarm_control_panel.{service}",
                        service_data={"entity_id": self._alarm_panel_entity},
                        description=f"Sync alarm panel to {new_armed.value}",
                    )
                ]

        return []

    def _handle_alarm_sync(self, intent: Intent) -> None:
        """Bidirectional sync from alarm panel state change (req #4)."""
        if self._syncing_alarm_panel:
            return

        new_panel_state = intent.data.get("new_state", "")
        mapped = _ALARM_STATE_MAP.get(new_panel_state)
        if mapped is None or mapped == self._armed_state:
            return

        old_state = self._armed_state
        self._armed_state = mapped
        _LOGGER.info(
            "Alarm panel sync: panel=%s → armed=%s (was %s)",
            new_panel_state,
            mapped.value,
            old_state.value,
        )
        async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)

    # =========================================================================
    # Action generation helpers
    # =========================================================================

    def _verdict_to_actions(
        self,
        verdict: EntryVerdict,
        entity_id: str,
    ) -> list[CoordinatorAction]:
        """Convert an entry verdict to coordinator actions."""
        if verdict in (EntryVerdict.SANCTIONED, EntryVerdict.LOG_ONLY):
            return [
                CoordinatorAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.LOW,
                    description=f"Entry {verdict.value}: {entity_id}",
                )
            ]

        if verdict == EntryVerdict.NOTIFY:
            return [
                NotificationAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.LOW,
                    message=f"Entry noted at {entity_id} — known person, unusual timing",
                    channels=["security"],
                    description=f"Entry notify: {entity_id}",
                )
            ]

        if verdict == EntryVerdict.INVESTIGATE:
            return [
                NotificationAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.MEDIUM,
                    message=f"Investigate entry at {entity_id} — armed, unrecognized",
                    channels=["security"],
                    description=f"Entry investigate: {entity_id}",
                )
            ]

        # ALERT or ALERT_HIGH
        self._active_alert = True
        self._alert_details = {
            "type": "entry_alert",
            "entity_id": entity_id,
            "verdict": verdict.value,
            "timestamp": dt_util.utcnow().isoformat(),
        }
        self._alerts_today += 1

        severity = (
            Severity.CRITICAL if verdict == EntryVerdict.ALERT_HIGH else Severity.HIGH
        )
        actions: list[CoordinatorAction] = []

        # Lock all doors
        actions.extend(
            self._generate_lockdown_actions(f"Security alert at {entity_id}")
        )

        # Security lights
        for light_id in self._security_light_entities:
            actions.append(
                ServiceCallAction(
                    coordinator_id=self.COORDINATOR_ID,
                    target_device=light_id,
                    severity=severity,
                    service="light.turn_on",
                    service_data={"entity_id": light_id, "brightness": 255},
                    description=f"Security light: {light_id}",
                )
            )

        # Camera recording trigger (uses platform-aware dispatcher)
        if self._camera_recording_enabled and self._camera_entities:
            actions.extend(
                self._camera_dispatcher._build_camera_actions(
                    self._camera_entities, self._camera_record_duration
                )
            )

        # Notification
        actions.append(
            NotificationAction(
                coordinator_id=self.COORDINATOR_ID,
                severity=severity,
                message=f"Security {verdict.value}: entry at {entity_id}",
                channels=["security"],
                description=f"Security alert notification: {entity_id}",
            )
        )

        return actions

    def _generate_lockdown_actions(
        self, reason: str
    ) -> list[ServiceCallAction]:
        """Generate actions to lock all doors and close garage doors."""
        actions: list[ServiceCallAction] = []

        for lock_id in self._lock_entities:
            actions.append(
                ServiceCallAction(
                    coordinator_id=self.COORDINATOR_ID,
                    target_device=lock_id,
                    severity=Severity.HIGH,
                    service="lock.lock",
                    service_data={"entity_id": lock_id},
                    description=f"Lock door ({reason}): {lock_id}",
                )
            )

        for garage_id in self._garage_entities:
            actions.append(
                ServiceCallAction(
                    coordinator_id=self.COORDINATOR_ID,
                    target_device=garage_id,
                    severity=Severity.HIGH,
                    service="cover.close_cover",
                    service_data={"entity_id": garage_id},
                    description=f"Close garage ({reason}): {garage_id}",
                )
            )

        return actions

    # =========================================================================
    # Periodic lock check (req #8 — armed-independent)
    # =========================================================================

    async def _evaluate_lock_check(self) -> list[CoordinatorAction]:
        """Check all locks and garage doors, lock any that are unlocked."""
        self._lock_checks_today += 1
        actions: list[CoordinatorAction] = []
        unlocked: list[str] = []
        unavailable: list[str] = []

        for lock_id in self._lock_entities:
            state = self.hass.states.get(lock_id)
            if state is None or state.state in ("unavailable", "unknown"):
                unavailable.append(lock_id)
                self._lock_compliance[lock_id] = "unavailable"
                continue
            self._lock_compliance[lock_id] = state.state
            if state.state == "unlocked":
                unlocked.append(lock_id)
                actions.append(
                    ServiceCallAction(
                        coordinator_id=self.COORDINATOR_ID,
                        target_device=lock_id,
                        severity=Severity.MEDIUM,
                        service="lock.lock",
                        service_data={"entity_id": lock_id},
                        description=f"Periodic lock check: locking {lock_id}",
                    )
                )

        for garage_id in self._garage_entities:
            state = self.hass.states.get(garage_id)
            if state is None or state.state in ("unavailable", "unknown"):
                unavailable.append(garage_id)
                self._lock_compliance[garage_id] = "unavailable"
                continue
            self._lock_compliance[garage_id] = state.state
            if state.state == "open":
                unlocked.append(garage_id)
                actions.append(
                    ServiceCallAction(
                        coordinator_id=self.COORDINATOR_ID,
                        target_device=garage_id,
                        severity=Severity.MEDIUM,
                        service="cover.close_cover",
                        service_data={"entity_id": garage_id},
                        description=f"Periodic lock check: closing {garage_id}",
                    )
                )

        if unavailable:
            _LOGGER.warning(
                "Periodic lock check: %d device(s) unavailable: %s",
                len(unavailable),
                ", ".join(unavailable),
            )
            actions.append(
                NotificationAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.MEDIUM,
                    message=f"Lock check: {len(unavailable)} device(s) offline: {', '.join(unavailable)}",
                    channels=["security"],
                    description="Lock check unavailable device notification",
                )
            )

        if unlocked:
            _LOGGER.info(
                "Periodic lock check: %d unlocked, locking: %s",
                len(unlocked),
                ", ".join(unlocked),
            )
            actions.append(
                NotificationAction(
                    coordinator_id=self.COORDINATOR_ID,
                    severity=Severity.MEDIUM,
                    message=f"Lock check: locked {len(unlocked)} door(s): {', '.join(unlocked)}",
                    channels=["security"],
                    description="Periodic lock check notification",
                )
            )

            # Compliance tracking
            if self.compliance_tracker is not None:
                for entity_id in unlocked:
                    self.compliance_tracker.schedule_check(
                        self.COORDINATOR_ID, entity_id, "locked"
                    )

        async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)
        return actions

    # =========================================================================
    # State listener callbacks
    # =========================================================================

    @callback
    def _handle_entry_sensor_change(self, event: Event) -> None:
        """Handle entry sensor state change → queue intent."""
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return

        from .manager import CoordinatorManager

        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return

        manager.queue_intent(
            Intent(
                source="state_change",
                entity_id=entity_id,
                data={
                    "new_state": new_state.state if new_state else "",
                    "old_state": old_state.state if old_state else "",
                },
                coordinator_id=self.COORDINATOR_ID,
            )
        )

    @callback
    def _handle_alarm_panel_change(self, event: Event) -> None:
        """Handle alarm panel state change → queue intent."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return

        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return

        manager.queue_intent(
            Intent(
                source="alarm_panel_change",
                entity_id=self._alarm_panel_entity or "",
                data={
                    "new_state": new_state.state if new_state else "",
                    "old_state": old_state.state if old_state else "",
                },
                coordinator_id=self.COORDINATOR_ID,
            )
        )

    @callback
    def _handle_periodic_lock_check(self, _now: Any = None) -> None:
        """Handle periodic lock check timer → queue intent."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return

        manager.queue_intent(
            Intent(
                source="periodic_lock_check",
                coordinator_id=self.COORDINATOR_ID,
            )
        )

    # =========================================================================
    # Service handlers
    # =========================================================================

    async def handle_arm(self, armed_state: str) -> None:
        """Handle security_arm service call."""
        try:
            new_state = ArmedState(armed_state)
        except ValueError:
            _LOGGER.warning("Invalid armed state: %s", armed_state)
            return

        old_state = self._armed_state
        self._armed_state = new_state
        _LOGGER.info("Armed state changed: %s → %s", old_state.value, new_state.value)

        # Sync to alarm panel if coupled
        if self._alarm_panel_entity:
            service = _ARMED_TO_ALARM_SERVICE.get(new_state)
            if service:
                self._syncing_alarm_panel = True
                try:
                    await self.hass.services.async_call(
                        "alarm_control_panel",
                        service,
                        {"entity_id": self._alarm_panel_entity},
                        blocking=True,
                    )
                finally:
                    self._syncing_alarm_panel = False

        async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)

    async def handle_disarm(self) -> None:
        """Handle security_disarm service call."""
        old_state = self._armed_state
        self._armed_state = ArmedState.DISARMED
        self._active_alert = False
        self._alert_details = {}
        _LOGGER.info("Disarmed (was %s)", old_state.value)

        if self._alarm_panel_entity:
            self._syncing_alarm_panel = True
            try:
                await self.hass.services.async_call(
                    "alarm_control_panel",
                    "alarm_disarm",
                    {"entity_id": self._alarm_panel_entity},
                    blocking=True,
                )
            finally:
                self._syncing_alarm_panel = False

        async_dispatcher_send(self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE)

    def handle_authorize_guest(
        self, person_name: str, expires_hours: float = 24
    ) -> None:
        """Handle authorize_guest service call."""
        self._sanction_checker.authorize_guest(person_name, expires_hours)
        _LOGGER.info("Guest authorized: %s for %.1f hours", person_name, expires_hours)

    def handle_add_expected_arrival(
        self, person_id: str, window_minutes: int = 30
    ) -> None:
        """Handle add_expected_arrival service call."""
        self._sanction_checker.add_expected_arrival(person_id, window_minutes)
        _LOGGER.info(
            "Expected arrival: %s within %d minutes", person_id, window_minutes
        )

    # =========================================================================
    # Public status methods (for sensors)
    # =========================================================================

    @property
    def armed_state(self) -> ArmedState:
        """Return the current armed state."""
        return self._armed_state

    @property
    def active_alert(self) -> bool:
        """Return whether an alert is active."""
        return self._active_alert

    @property
    def alert_details(self) -> dict[str, Any]:
        """Return current alert details."""
        return self._alert_details

    @property
    def last_entry_event(self) -> dict[str, Any]:
        """Return last entry event data."""
        return self._last_entry_event

    @property
    def lock_compliance(self) -> dict[str, str]:
        """Return lock compliance status."""
        return self._lock_compliance

    def get_security_status(self) -> str:
        """Return overall security status string."""
        if self._active_alert:
            return "alert"
        if self._armed_state == ArmedState.DISARMED:
            return "disarmed"
        return "armed"

    def get_compliance_summary(self) -> dict[str, Any]:
        """Return lock compliance summary."""
        total = len(self._lock_entities) + len(self._garage_entities)
        locked = sum(
            1
            for v in self._lock_compliance.values()
            if v in ("locked", "closed")
        )
        return {
            "total_devices": total,
            "compliant": locked,
            "non_compliant": total - locked,
            "compliance_rate": round(locked / total * 100, 1) if total > 0 else 100.0,
            "last_check": dt_util.utcnow().isoformat(),
            "checks_today": self._lock_checks_today,
        }

    def get_diagnostics_status(self) -> str:
        """Return diagnostics health status."""
        if self.anomaly_detector is None:
            return "degraded"
        return "healthy"

    def get_anomaly_status(self) -> str:
        """Return anomaly status string."""
        if self.anomaly_detector is None:
            return "not_configured"
        learning = self.anomaly_detector.get_learning_status()
        if hasattr(learning, "value") and learning.value in (
            "insufficient_data",
            "learning",
        ):
            return learning.value
        return self.anomaly_detector.get_worst_severity().value

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _maybe_reset_daily_counters(self) -> None:
        """Reset daily counters if the date has changed."""
        today = dt_util.now().date().isoformat()
        if today != self._last_reset_date:
            self._alerts_today = 0
            self._lock_checks_today = 0
            self._last_reset_date = today

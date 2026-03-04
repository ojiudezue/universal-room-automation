"""Notification Manager — centralized outbound notification delivery.

Handles 5 channel types (Pushover, Companion App, WhatsApp, TTS, Alert Lights)
with severity-based routing, per-person config, ack/cooldown/re-fire for
CRITICAL alerts, quiet hours, daily digest mode, and SQLite persistence.

v3.6.29: Initial implementation (C4a).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_change,
)
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_NM_ALERT_LIGHTS,
    CONF_NM_COMPANION_ENABLED,
    CONF_NM_COMPANION_SEVERITY,
    CONF_NM_COOLDOWN_CO,
    CONF_NM_COOLDOWN_DEFAULT,
    CONF_NM_COOLDOWN_FLOODING,
    CONF_NM_COOLDOWN_FREEZE,
    CONF_NM_COOLDOWN_INTRUSION,
    CONF_NM_COOLDOWN_SMOKE,
    CONF_NM_COOLDOWN_WATER_LEAK,
    CONF_NM_ENABLED,
    CONF_NM_LIGHTS_ENABLED,
    CONF_NM_LIGHTS_SEVERITY,
    CONF_NM_PERSONS,
    CONF_NM_PERSON_COMPANION_SERVICE,
    CONF_NM_PERSON_DELIVERY_PREF,
    CONF_NM_PERSON_DIGEST_EVENING,
    CONF_NM_PERSON_DIGEST_EVENING_ENABLED,
    CONF_NM_PERSON_DIGEST_MORNING,
    CONF_NM_PERSON_ENTITY,
    CONF_NM_PERSON_PUSHOVER_KEY,
    CONF_NM_PERSON_WHATSAPP_PHONE,
    CONF_NM_PUSHOVER_ENABLED,
    CONF_NM_PUSHOVER_SERVICE,
    CONF_NM_PUSHOVER_SEVERITY,
    CONF_NM_QUIET_MANUAL_END,
    CONF_NM_QUIET_MANUAL_START,
    CONF_NM_QUIET_USE_HOUSE_STATE,
    CONF_NM_TTS_ENABLED,
    CONF_NM_TTS_SEVERITY,
    CONF_NM_TTS_SPEAKERS,
    CONF_NM_WHATSAPP_ENABLED,
    CONF_NM_WHATSAPP_SEVERITY,
    DEFAULT_NM_COMPANION_SEVERITY,
    DEFAULT_NM_COOLDOWN_CO,
    DEFAULT_NM_COOLDOWN_DEFAULT,
    DEFAULT_NM_COOLDOWN_FLOODING,
    DEFAULT_NM_COOLDOWN_FREEZE,
    DEFAULT_NM_COOLDOWN_INTRUSION,
    DEFAULT_NM_COOLDOWN_SMOKE,
    DEFAULT_NM_COOLDOWN_WATER_LEAK,
    DEFAULT_NM_LIGHTS_SEVERITY,
    DEFAULT_NM_PUSHOVER_SEVERITY,
    DEFAULT_NM_TTS_SEVERITY,
    DEFAULT_NM_WHATSAPP_SEVERITY,
    DOMAIN,
    NM_CRITICAL_REPEAT_INTERVAL,
    NM_DEDUP_CRITICAL,
    NM_DEDUP_HIGH,
    NM_DEDUP_LOW,
    NM_DEDUP_MEDIUM,
    NM_DELIVERY_DIGEST,
    NM_DELIVERY_IMMEDIATE,
    NM_DELIVERY_OFF,
    RETENTION_NOTIFICATION_LOG,
    VERSION,
)
from .base import Severity
from .signals import SIGNAL_NM_ALERT_STATE_CHANGED, SIGNAL_NM_ENTITIES_UPDATE

_LOGGER = logging.getLogger(__name__)


class AlertState(StrEnum):
    """Notification Manager alert state machine states."""

    IDLE = "idle"
    ALERTING = "alerting"
    REPEATING = "repeating"
    COOLDOWN = "cooldown"
    RE_EVALUATE = "re_evaluate"


# Severity string to Severity enum mapping
SEVERITY_MAP: dict[str, Severity] = {
    "LOW": Severity.LOW,
    "MEDIUM": Severity.MEDIUM,
    "HIGH": Severity.HIGH,
    "CRITICAL": Severity.CRITICAL,
}

# Dedup windows per severity (seconds)
DEDUP_WINDOWS: dict[Severity, int] = {
    Severity.CRITICAL: NM_DEDUP_CRITICAL,
    Severity.HIGH: NM_DEDUP_HIGH,
    Severity.MEDIUM: NM_DEDUP_MEDIUM,
    Severity.LOW: NM_DEDUP_LOW,
}

# Light patterns consolidated from Safety + Security
LIGHT_PATTERNS: dict[str, dict[str, Any]] = {
    "fire": {"color": (255, 100, 0), "effect": "flash", "interval_ms": 250},
    "smoke": {"color": (255, 100, 0), "effect": "flash", "interval_ms": 250},
    "water_leak": {"color": (0, 0, 255), "effect": "pulse", "interval_ms": 1000},
    "flooding": {"color": (0, 0, 255), "effect": "pulse", "interval_ms": 500},
    "carbon_monoxide": {"color": (255, 100, 0), "effect": "flash", "interval_ms": 500},
    "co": {"color": (255, 100, 0), "effect": "flash", "interval_ms": 500},
    "freeze_risk": {"color": (100, 150, 255), "effect": "pulse", "interval_ms": 1000},
    "warning": {"color": (255, 255, 0), "effect": "pulse", "interval_ms": 1000},
    "intruder": {"color": (255, 0, 0), "effect": "flash", "interval_ms": 200},
    "armed": {"color": (255, 0, 0), "effect": "solid", "brightness": 30},
    "investigate": {"color": (255, 255, 0), "effect": "pulse", "interval_ms": 800},
    "arriving": {"color": (255, 180, 100), "effect": "fade", "interval_ms": 2000},
    "sequential": {"color": None, "effect": "sequential", "interval_ms": 300},
}

# Cooldown config key mapping
COOLDOWN_CONFIG: dict[str, tuple[str, int]] = {
    "smoke": (CONF_NM_COOLDOWN_SMOKE, DEFAULT_NM_COOLDOWN_SMOKE),
    "fire": (CONF_NM_COOLDOWN_SMOKE, DEFAULT_NM_COOLDOWN_SMOKE),
    "carbon_monoxide": (CONF_NM_COOLDOWN_CO, DEFAULT_NM_COOLDOWN_CO),
    "co": (CONF_NM_COOLDOWN_CO, DEFAULT_NM_COOLDOWN_CO),
    "flooding": (CONF_NM_COOLDOWN_FLOODING, DEFAULT_NM_COOLDOWN_FLOODING),
    "water_leak": (CONF_NM_COOLDOWN_WATER_LEAK, DEFAULT_NM_COOLDOWN_WATER_LEAK),
    "freeze_risk": (CONF_NM_COOLDOWN_FREEZE, DEFAULT_NM_COOLDOWN_FREEZE),
    "intrusion": (CONF_NM_COOLDOWN_INTRUSION, DEFAULT_NM_COOLDOWN_INTRUSION),
}


class NotificationManager:
    """Centralized notification delivery for all domain coordinators.

    NOT a BaseCoordinator subclass — does not manage rooms or participate
    in intent/evaluate/action pipeline. Standalone service owned by
    CoordinatorManager, stored in hass.data[DOMAIN]["notification_manager"].
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
    ) -> None:
        """Initialize the Notification Manager."""
        self.hass = hass
        self._config = config

        # State
        self._alert_state = AlertState.IDLE
        self._active_alert_data: dict[str, Any] | None = None
        self._repeat_unsub: CALLBACK_TYPE | None = None
        self._cooldown_unsub: CALLBACK_TYPE | None = None
        self._countdown_task: asyncio.Task | None = None
        self._digest_unsubs: list[CALLBACK_TYPE] = []
        self._action_unsub: CALLBACK_TYPE | None = None

        # Runtime caches
        self._dedup_cache: dict[str, float] = {}
        self._channel_health: dict[str, dict[str, Any]] = {
            "pushover": {"status": "ok", "last_success": None, "failures": 0},
            "companion": {"status": "ok", "last_success": None, "failures": 0},
            "whatsapp": {"status": "ok", "last_success": None, "failures": 0},
            "tts": {"status": "ok", "last_success": None, "failures": 0},
            "lights": {"status": "ok", "last_success": None, "failures": 0},
        }
        self._light_original_states: dict[str, dict[str, Any]] = {}
        self._light_pattern_task: asyncio.Task | None = None

        # Sensor caches
        self._last_notification: dict[str, Any] | None = None
        self._notifications_today_count: int = 0
        self._cooldown_remaining: int = 0
        self._cooldown_hazard_type: str | None = None
        self._cooldown_location: str | None = None

        # Diagnostic counters (for anomaly/delivery/diagnostics sensors)
        self._send_attempts: int = 0
        self._send_successes: int = 0
        self._send_failures: int = 0
        self._dedup_suppressions: int = 0
        self._quiet_suppressions: int = 0
        self._notifications_by_severity: dict[str, int] = {
            "LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0,
        }
        self._notifications_by_channel: dict[str, int] = {
            "pushover": 0, "companion": 0, "whatsapp": 0, "tts": 0, "lights": 0,
        }
        # Rolling window for anomaly detection (hourly counts, last 24h)
        self._hourly_counts: list[int] = [0] * 24
        self._current_hour_idx: int = -1

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the NM device."""
        return DeviceInfo(
            identifiers={(DOMAIN, "notification_manager")},
            name="URA: Notification Manager",
            manufacturer="Universal Room Automation",
            model="Notification Manager",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def enabled(self) -> bool:
        """Return whether NM is enabled."""
        return self._config.get(CONF_NM_ENABLED, False)

    @property
    def alert_state(self) -> AlertState:
        """Return the current alert state."""
        return self._alert_state

    @property
    def active_alert(self) -> bool:
        """Return whether there is an active (unacknowledged) alert."""
        return self._alert_state in (AlertState.ALERTING, AlertState.REPEATING)

    @property
    def cooldown_remaining(self) -> int:
        """Return seconds remaining in cooldown (0 if not in cooldown)."""
        return self._cooldown_remaining

    @property
    def channel_status(self) -> dict[str, dict[str, Any]]:
        """Return per-channel health status."""
        return self._channel_health

    @property
    def last_notification(self) -> dict[str, Any] | None:
        """Return the last notification data."""
        return self._last_notification

    @property
    def notifications_today(self) -> int:
        """Return count of notifications today."""
        return self._notifications_today_count

    @property
    def delivery_rate(self) -> float:
        """Return delivery success rate (0-100%)."""
        if self._send_attempts == 0:
            return 100.0
        return round(self._send_successes / self._send_attempts * 100, 1)

    @property
    def diagnostics_summary(self) -> dict[str, Any]:
        """Return diagnostic summary for the diagnostics sensor."""
        return {
            "send_attempts": self._send_attempts,
            "send_successes": self._send_successes,
            "send_failures": self._send_failures,
            "delivery_rate": self.delivery_rate,
            "dedup_suppressions": self._dedup_suppressions,
            "quiet_suppressions": self._quiet_suppressions,
            "by_severity": dict(self._notifications_by_severity),
            "by_channel": dict(self._notifications_by_channel),
        }

    @property
    def anomaly_status(self) -> str:
        """Return anomaly status based on notification volume patterns.

        Uses a simple heuristic: if current hour's count exceeds 3x the
        rolling average, flag as advisory/alert.
        """
        if self._notifications_today_count == 0:
            return "nominal"
        # Need at least a few hours of data
        non_zero = [c for c in self._hourly_counts if c > 0]
        if len(non_zero) < 2:
            return "learning"
        avg = sum(self._hourly_counts) / max(len(non_zero), 1)
        if avg == 0:
            return "nominal"
        current = self._hourly_counts[self._current_hour_idx] if self._current_hour_idx >= 0 else 0
        ratio = current / avg
        if ratio > 5:
            return "alert"
        if ratio > 3:
            return "advisory"
        return "nominal"

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def async_setup(self) -> None:
        """Set up the Notification Manager — recover state, prune DB, set up digest timers."""
        if not self.enabled:
            _LOGGER.info("Notification Manager disabled")
            return

        _LOGGER.info("Notification Manager starting setup")

        # Prune old notifications
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database:
            pruned = await database.prune_notification_log(RETENTION_NOTIFICATION_LOG)
            if pruned:
                _LOGGER.info("Pruned %d old notification log entries", pruned)

        # Recover state from DB
        await self._recover_state_from_db()

        # Set up digest timers
        self._setup_digest_timers()

        # Subscribe to companion app action events
        self._action_unsub = self.hass.bus.async_listen(
            "mobile_app_notification_action", self._handle_companion_action
        )

        _LOGGER.info(
            "Notification Manager ready (state=%s, today=%d)",
            self._alert_state,
            self._notifications_today_count,
        )

    async def async_teardown(self) -> None:
        """Tear down the Notification Manager."""
        # Cancel repeat timer
        if self._repeat_unsub:
            self._repeat_unsub()
            self._repeat_unsub = None

        # Cancel cooldown timer
        if self._cooldown_unsub:
            self._cooldown_unsub()
            self._cooldown_unsub = None

        # Cancel digest timers
        for unsub in self._digest_unsubs:
            unsub()
        self._digest_unsubs.clear()

        # Cancel countdown task
        if self._countdown_task and not self._countdown_task.done():
            self._countdown_task.cancel()
            self._countdown_task = None

        # Cancel action listener
        if self._action_unsub:
            self._action_unsub()
            self._action_unsub = None

        # Cancel light pattern
        if self._light_pattern_task and not self._light_pattern_task.done():
            self._light_pattern_task.cancel()
            try:
                await self._light_pattern_task
            except (asyncio.CancelledError, Exception):
                pass
            self._light_pattern_task = None

        # Restore lights if active
        await self._restore_alert_lights()

        _LOGGER.info("Notification Manager stopped")

    # =========================================================================
    # Core notification entry point
    # =========================================================================

    async def async_notify(
        self,
        coordinator_id: str,
        severity: Severity,
        title: str,
        message: str,
        hazard_type: str | None = None,
        location: str | None = None,
    ) -> None:
        """Main notification entry point — called by coordinators.

        Routes to appropriate channels based on severity and config.
        """
        if not self.enabled:
            return

        # Quiet hours check (CRITICAL bypasses)
        if severity != Severity.CRITICAL and self._is_quiet_hours():
            _LOGGER.debug("Notification suppressed during quiet hours: %s", title)
            self._quiet_suppressions += 1
            return

        # Dedup check
        if self._is_deduplicated(coordinator_id, title, location, severity):
            _LOGGER.debug("Notification deduplicated: %s", title)
            self._dedup_suppressions += 1
            return

        severity_str = severity.name
        database = self.hass.data.get(DOMAIN, {}).get("database")
        now_str = dt_util.utcnow().isoformat()

        _LOGGER.info(
            "NM notify: coordinator=%s severity=%s title=%s",
            coordinator_id, severity_str, title,
        )

        # Determine which channels qualify by severity threshold
        channels_fired: list[str] = []

        # --- Global channels (TTS, Alert Lights) — always immediate ---
        if self._channel_qualifies("tts", severity):
            await self._send_tts(title, message)
            channels_fired.append("tts")
            if database:
                await database.log_notification(
                    coordinator_id, severity_str, title, message,
                    hazard_type, location, None, "tts", 1,
                )

        if self._channel_qualifies("lights", severity):
            await self._trigger_alert_lights(hazard_type or "warning", severity)
            channels_fired.append("lights")
            if database:
                await database.log_notification(
                    coordinator_id, severity_str, title, message,
                    hazard_type, location, None, "lights", 1,
                )

        # --- Per-person channels ---
        persons = self._config.get(CONF_NM_PERSONS, [])
        for person_cfg in persons:
            person_id = person_cfg.get(CONF_NM_PERSON_ENTITY, "")
            delivery_pref = person_cfg.get(CONF_NM_PERSON_DELIVERY_PREF, NM_DELIVERY_IMMEDIATE)

            # CRITICAL/HIGH always immediate
            if severity in (Severity.CRITICAL, Severity.HIGH):
                effective_pref = NM_DELIVERY_IMMEDIATE
            else:
                effective_pref = delivery_pref

            if effective_pref == NM_DELIVERY_OFF:
                continue

            # Pushover
            if self._channel_qualifies("pushover", severity):
                pushover_key = person_cfg.get(CONF_NM_PERSON_PUSHOVER_KEY, "")
                if pushover_key:
                    if effective_pref == NM_DELIVERY_IMMEDIATE:
                        await self._send_pushover(title, message, severity, pushover_key)
                        channels_fired.append("pushover")
                        if database:
                            await database.log_notification(
                                coordinator_id, severity_str, title, message,
                                hazard_type, location, person_id, "pushover", 1,
                            )
                    elif effective_pref == NM_DELIVERY_DIGEST:
                        if database:
                            await database.log_notification(
                                coordinator_id, severity_str, title, message,
                                hazard_type, location, person_id, "pushover", 0,
                            )

            # Companion App
            if self._channel_qualifies("companion", severity):
                companion_svc = person_cfg.get(CONF_NM_PERSON_COMPANION_SERVICE, "")
                if companion_svc:
                    if effective_pref == NM_DELIVERY_IMMEDIATE:
                        await self._send_companion(
                            title, message, severity, companion_svc,
                            is_critical=(severity == Severity.CRITICAL),
                        )
                        channels_fired.append("companion")
                        if database:
                            await database.log_notification(
                                coordinator_id, severity_str, title, message,
                                hazard_type, location, person_id, "companion", 1,
                            )
                    elif effective_pref == NM_DELIVERY_DIGEST:
                        if database:
                            await database.log_notification(
                                coordinator_id, severity_str, title, message,
                                hazard_type, location, person_id, "companion", 0,
                            )

            # WhatsApp
            if self._channel_qualifies("whatsapp", severity):
                phone = person_cfg.get(CONF_NM_PERSON_WHATSAPP_PHONE, "")
                if phone:
                    if effective_pref == NM_DELIVERY_IMMEDIATE:
                        await self._send_whatsapp(title, message, phone)
                        channels_fired.append("whatsapp")
                        if database:
                            await database.log_notification(
                                coordinator_id, severity_str, title, message,
                                hazard_type, location, person_id, "whatsapp", 1,
                            )
                    elif effective_pref == NM_DELIVERY_DIGEST:
                        if database:
                            await database.log_notification(
                                coordinator_id, severity_str, title, message,
                                hazard_type, location, person_id, "whatsapp", 0,
                            )

        # Update sensor caches
        self._last_notification = {
            "severity": severity_str,
            "coordinator": coordinator_id,
            "title": title,
            "message": message,
            "hazard_type": hazard_type,
            "location": location,
            "channels": channels_fired,
            "timestamp": now_str,
        }
        self._notifications_today_count += 1
        self._notifications_by_severity[severity_str] = (
            self._notifications_by_severity.get(severity_str, 0) + 1
        )
        self._update_hourly_count()

        # Fire entity updates
        async_dispatcher_send(self.hass, SIGNAL_NM_ENTITIES_UPDATE)

        # CRITICAL: start ack/repeat engine
        if severity == Severity.CRITICAL:
            await self._enter_alerting(
                coordinator_id, severity_str, title, message,
                hazard_type, location,
            )

    # =========================================================================
    # Channel dispatchers
    # =========================================================================

    async def _send_pushover(
        self,
        title: str,
        message: str,
        severity: Severity,
        user_key: str,
    ) -> None:
        """Send notification via Pushover."""
        service_name = self._config.get(CONF_NM_PUSHOVER_SERVICE, "notify.pushover")
        try:
            domain, service = service_name.split(".", 1)
            data: dict[str, Any] = {
                "title": title,
                "message": message,
                "target": user_key,
            }
            # Set priority based on severity
            if severity == Severity.CRITICAL:
                data["data"] = {"priority": 1, "sound": "siren"}
            elif severity == Severity.HIGH:
                data["data"] = {"priority": 1}
            await self.hass.services.async_call(domain, service, data, blocking=True)
            self._update_channel_health("pushover", True)
        except Exception as e:
            _LOGGER.error("Pushover send failed: %s", e)
            self._update_channel_health("pushover", False)

    async def _send_companion(
        self,
        title: str,
        message: str,
        severity: Severity,
        service_name: str,
        is_critical: bool = False,
    ) -> None:
        """Send notification via HA Companion App."""
        try:
            domain, service = service_name.split(".", 1)
            data: dict[str, Any] = {
                "title": title,
                "message": message,
            }
            if is_critical:
                data["data"] = {
                    "actions": [
                        {
                            "action": "ACKNOWLEDGE_URA",
                            "title": "Acknowledge",
                        }
                    ],
                    "push": {"sound": {"name": "default", "critical": 1, "volume": 1.0}},
                }
            await self.hass.services.async_call(domain, service, data, blocking=True)
            self._update_channel_health("companion", True)
        except Exception as e:
            _LOGGER.error("Companion app send failed: %s", e)
            self._update_channel_health("companion", False)

    async def _send_whatsapp(self, title: str, message: str, phone: str) -> None:
        """Send notification via WhatsApp (ha-wa-bridge)."""
        try:
            await self.hass.services.async_call(
                "whatsapp", "send_message",
                {"phone": phone, "body": f"*{title}*\n{message}"},
                blocking=True,
            )
            self._update_channel_health("whatsapp", True)
        except Exception as e:
            _LOGGER.error("WhatsApp send failed: %s", e)
            self._update_channel_health("whatsapp", False)

    async def _send_tts(self, title: str, message: str) -> None:
        """Send TTS announcement to configured speakers."""
        speakers = self._config.get(CONF_NM_TTS_SPEAKERS, [])
        if not speakers:
            return
        try:
            for speaker in speakers:
                await self.hass.services.async_call(
                    "tts", "speak",
                    {
                        "media_player_entity_id": speaker,
                        "message": f"{title}. {message}",
                    },
                    blocking=False,
                )
            self._update_channel_health("tts", True)
        except Exception as e:
            _LOGGER.error("TTS send failed: %s", e)
            self._update_channel_health("tts", False)

    # =========================================================================
    # Alert lights
    # =========================================================================

    async def _trigger_alert_lights(
        self, hazard_type: str, severity: Severity
    ) -> None:
        """Activate alert light pattern for a hazard type."""
        light_entities = self._config.get(CONF_NM_ALERT_LIGHTS, [])
        if not light_entities:
            return

        pattern = LIGHT_PATTERNS.get(hazard_type, LIGHT_PATTERNS["warning"])

        # Save original states before first activation
        if not self._light_original_states:
            await self._store_alert_light_states(light_entities)

        # Cancel existing pattern
        if self._light_pattern_task and not self._light_pattern_task.done():
            self._light_pattern_task.cancel()

        # Start new pattern
        self._light_pattern_task = self.hass.async_create_task(
            self._run_light_pattern(light_entities, pattern)
        )
        self._update_channel_health("lights", True)

    async def _store_alert_light_states(self, entities: list[str]) -> None:
        """Save current light states for later restoration."""
        for entity_id in entities:
            state = self.hass.states.get(entity_id)
            if state:
                self._light_original_states[entity_id] = {
                    "state": state.state,
                    "brightness": state.attributes.get("brightness"),
                    "rgb_color": state.attributes.get("rgb_color"),
                    "color_temp": state.attributes.get("color_temp"),
                }

    async def _restore_alert_lights(self) -> None:
        """Restore lights to their pre-alert states."""
        for entity_id, orig in self._light_original_states.items():
            try:
                if orig["state"] == "off":
                    await self.hass.services.async_call(
                        "light", "turn_off", {"entity_id": entity_id}, blocking=False
                    )
                else:
                    svc_data: dict[str, Any] = {"entity_id": entity_id}
                    if orig.get("brightness"):
                        svc_data["brightness"] = orig["brightness"]
                    if orig.get("rgb_color"):
                        svc_data["rgb_color"] = orig["rgb_color"]
                    elif orig.get("color_temp"):
                        svc_data["color_temp"] = orig["color_temp"]
                    await self.hass.services.async_call(
                        "light", "turn_on", svc_data, blocking=False
                    )
            except Exception as e:
                _LOGGER.warning("Failed to restore light %s: %s", entity_id, e)
        self._light_original_states.clear()

    async def _run_light_pattern(
        self, entities: list[str], pattern: dict[str, Any]
    ) -> None:
        """Run a light pattern until cancelled."""
        effect = pattern.get("effect", "flash")
        color = pattern.get("color")
        interval = pattern.get("interval_ms", 500) / 1000.0
        brightness = pattern.get("brightness", 255)

        try:
            if effect == "solid":
                svc_data: dict[str, Any] = {
                    "entity_id": entities,
                    "brightness": brightness,
                }
                if color:
                    svc_data["rgb_color"] = list(color)
                await self.hass.services.async_call(
                    "light", "turn_on", svc_data, blocking=False
                )
                return

            cycle = 0
            while True:
                if effect == "flash":
                    if cycle % 2 == 0:
                        svc_data = {"entity_id": entities, "brightness": 255}
                        if color:
                            svc_data["rgb_color"] = list(color)
                        await self.hass.services.async_call(
                            "light", "turn_on", svc_data, blocking=False
                        )
                    else:
                        await self.hass.services.async_call(
                            "light", "turn_off", {"entity_id": entities}, blocking=False
                        )
                elif effect == "pulse":
                    br = 255 if cycle % 2 == 0 else 50
                    svc_data = {"entity_id": entities, "brightness": br}
                    if color:
                        svc_data["rgb_color"] = list(color)
                    await self.hass.services.async_call(
                        "light", "turn_on", svc_data, blocking=False
                    )
                elif effect == "sequential":
                    idx = cycle % len(entities)
                    # Turn all off, then turn one on
                    await self.hass.services.async_call(
                        "light", "turn_off", {"entity_id": entities}, blocking=False
                    )
                    await self.hass.services.async_call(
                        "light", "turn_on",
                        {"entity_id": entities[idx], "brightness": 255},
                        blocking=False,
                    )
                elif effect == "fade":
                    svc_data = {"entity_id": entities, "brightness": 255, "transition": interval}
                    if color:
                        svc_data["rgb_color"] = list(color)
                    await self.hass.services.async_call(
                        "light", "turn_on", svc_data, blocking=False
                    )
                    return  # fade is a one-shot

                cycle += 1
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("Light pattern error: %s", e)

    # =========================================================================
    # Ack / Cooldown / Re-fire engine
    # =========================================================================

    async def _enter_alerting(
        self,
        coordinator_id: str,
        severity_str: str,
        title: str,
        message: str,
        hazard_type: str | None,
        location: str | None,
    ) -> None:
        """Enter ALERTING state for a CRITICAL notification."""
        # Cancel any existing cooldown/countdown from a previous alert
        if self._cooldown_unsub:
            self._cooldown_unsub()
            self._cooldown_unsub = None
        if self._countdown_task and not self._countdown_task.done():
            self._countdown_task.cancel()
            self._countdown_task = None
        self._cooldown_remaining = 0

        self._alert_state = AlertState.ALERTING
        self._active_alert_data = {
            "coordinator_id": coordinator_id,
            "severity": severity_str,
            "title": title,
            "message": message,
            "hazard_type": hazard_type,
            "location": location,
        }

        async_dispatcher_send(self.hass, SIGNAL_NM_ALERT_STATE_CHANGED)

        # Start repeat timer
        self._alert_state = AlertState.REPEATING
        self._schedule_repeat()

    def _schedule_repeat(self) -> None:
        """Schedule the next repeat notification."""
        if self._repeat_unsub:
            self._repeat_unsub()
        self._repeat_unsub = async_call_later(
            self.hass, NM_CRITICAL_REPEAT_INTERVAL, self._repeat_alert
        )

    async def _repeat_alert(self, _now: Any = None) -> None:
        """Repeat the active CRITICAL alert."""
        if not self.enabled:
            return
        if self._alert_state != AlertState.REPEATING or not self._active_alert_data:
            return

        data = self._active_alert_data
        _LOGGER.info("Repeating CRITICAL alert: %s", data.get("title"))

        # Re-send to all qualifying channels
        persons = self._config.get(CONF_NM_PERSONS, [])
        for person_cfg in persons:
            if self._channel_qualifies("pushover", Severity.CRITICAL):
                key = person_cfg.get(CONF_NM_PERSON_PUSHOVER_KEY, "")
                if key:
                    await self._send_pushover(
                        data["title"], data["message"], Severity.CRITICAL, key
                    )
            if self._channel_qualifies("companion", Severity.CRITICAL):
                svc = person_cfg.get(CONF_NM_PERSON_COMPANION_SERVICE, "")
                if svc:
                    await self._send_companion(
                        data["title"], data["message"], Severity.CRITICAL, svc,
                        is_critical=True,
                    )

        # TTS repeat
        if self._channel_qualifies("tts", Severity.CRITICAL):
            await self._send_tts(data["title"], data["message"])

        # Schedule next repeat
        self._schedule_repeat()

    async def async_acknowledge(self) -> None:
        """Acknowledge the active alert — stops repeating, starts cooldown."""
        if self._alert_state not in (AlertState.ALERTING, AlertState.REPEATING):
            _LOGGER.debug("No active alert to acknowledge")
            return

        _LOGGER.info("Alert acknowledged")

        # Cancel repeat
        if self._repeat_unsub:
            self._repeat_unsub()
            self._repeat_unsub = None

        # Cancel light pattern
        if self._light_pattern_task and not self._light_pattern_task.done():
            self._light_pattern_task.cancel()
            self._light_pattern_task = None
        await self._restore_alert_lights()

        # Mark acknowledged in DB
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database:
            await database.acknowledge_notification()

        # Start cooldown
        await self._start_cooldown()

    async def _start_cooldown(self) -> None:
        """Start the post-ack cooldown period."""
        if not self._active_alert_data:
            self._alert_state = AlertState.IDLE
            async_dispatcher_send(self.hass, SIGNAL_NM_ALERT_STATE_CHANGED)
            return

        hazard_type = self._active_alert_data.get("hazard_type", "")
        conf_key, default_mins = COOLDOWN_CONFIG.get(
            hazard_type or "", (CONF_NM_COOLDOWN_DEFAULT, DEFAULT_NM_COOLDOWN_DEFAULT)
        )
        cooldown_mins = int(self._config.get(conf_key, default_mins))
        cooldown_secs = cooldown_mins * 60

        self._alert_state = AlertState.COOLDOWN
        self._cooldown_remaining = cooldown_secs
        self._cooldown_hazard_type = hazard_type
        self._cooldown_location = self._active_alert_data.get("location")

        # Set cooldown in DB
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database:
            expires = (dt_util.utcnow() + timedelta(seconds=cooldown_secs)).isoformat()
            active = await database.get_active_critical()
            # Use the most recent critical — it was just acknowledged
            active_cd = await database.get_active_cooldown()
            if active:
                await database.set_cooldown(active["id"], expires)
            elif active_cd:
                await database.set_cooldown(active_cd["id"], expires)

        async_dispatcher_send(self.hass, SIGNAL_NM_ALERT_STATE_CHANGED)
        async_dispatcher_send(self.hass, SIGNAL_NM_ENTITIES_UPDATE)

        # Schedule cooldown expiry
        self._cooldown_unsub = async_call_later(
            self.hass, cooldown_secs, self._cooldown_expired
        )

        # Cancel existing countdown if any
        if self._countdown_task and not self._countdown_task.done():
            self._countdown_task.cancel()
        # Start countdown updater
        self._countdown_task = self.hass.async_create_task(self._countdown_tick())

    async def _countdown_tick(self) -> None:
        """Update cooldown_remaining every 10 seconds."""
        while self._alert_state == AlertState.COOLDOWN and self._cooldown_remaining > 0:
            await asyncio.sleep(10)
            self._cooldown_remaining = max(0, self._cooldown_remaining - 10)
            async_dispatcher_send(self.hass, SIGNAL_NM_ENTITIES_UPDATE)

    async def _cooldown_expired(self, _now: Any = None) -> None:
        """Handle cooldown expiry — re-evaluate if hazard still active."""
        if self._alert_state != AlertState.COOLDOWN:
            return

        self._cooldown_unsub = None
        self._cooldown_remaining = 0
        self._alert_state = AlertState.RE_EVALUATE

        _LOGGER.info("Cooldown expired, re-evaluating hazard")

        await self._re_evaluate_hazard()

    async def _re_evaluate_hazard(self) -> None:
        """Check if the hazard is still active after cooldown."""
        if not self._active_alert_data:
            self._alert_state = AlertState.IDLE
            self._active_alert_data = None
            async_dispatcher_send(self.hass, SIGNAL_NM_ALERT_STATE_CHANGED)
            async_dispatcher_send(self.hass, SIGNAL_NM_ENTITIES_UPDATE)
            return

        hazard_type = self._active_alert_data.get("hazard_type", "")
        location = self._active_alert_data.get("location", "")
        coordinator_id = self._active_alert_data.get("coordinator_id", "")

        # Query source coordinator
        coordinator_manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        still_active = False
        if coordinator_manager:
            coordinator = coordinator_manager.coordinators.get(coordinator_id)
            if coordinator:
                still_active = coordinator.is_hazard_active(hazard_type, location)

        if still_active:
            _LOGGER.warning(
                "Hazard %s at %s still active after cooldown — re-firing",
                hazard_type, location,
            )
            data = self._active_alert_data
            await self.async_notify(
                coordinator_id=data["coordinator_id"],
                severity=Severity.CRITICAL,
                title=data["title"],
                message=data["message"],
                hazard_type=data.get("hazard_type"),
                location=data.get("location"),
            )
        else:
            _LOGGER.info("Hazard cleared after cooldown — returning to idle")
            self._alert_state = AlertState.IDLE
            self._active_alert_data = None
            async_dispatcher_send(self.hass, SIGNAL_NM_ALERT_STATE_CHANGED)
            async_dispatcher_send(self.hass, SIGNAL_NM_ENTITIES_UPDATE)

    # =========================================================================
    # Companion App action handler
    # =========================================================================

    @callback
    def _handle_companion_action(self, event: Event) -> None:
        """Handle companion app notification action button press."""
        action = event.data.get("action", "")
        if action == "ACKNOWLEDGE_URA":
            self.hass.async_create_task(self.async_acknowledge())

    # =========================================================================
    # Quiet hours
    # =========================================================================

    def _is_quiet_hours(self) -> bool:
        """Check if we're currently in quiet hours."""
        use_house_state = self._config.get(CONF_NM_QUIET_USE_HOUSE_STATE, True)

        if use_house_state:
            coordinator_manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if coordinator_manager:
                state_str = str(coordinator_manager.house_state).lower()
                return state_str in ("sleep", "home_night")
            return False

        # Manual schedule
        start = self._config.get(CONF_NM_QUIET_MANUAL_START, "22:00")
        end = self._config.get(CONF_NM_QUIET_MANUAL_END, "07:00")
        now = dt_util.now().strftime("%H:%M")

        if start <= end:
            return start <= now <= end
        # Overnight range (e.g., 22:00 - 07:00)
        return now >= start or now <= end

    # =========================================================================
    # Deduplication
    # =========================================================================

    def _is_deduplicated(
        self,
        coordinator_id: str,
        title: str,
        location: str | None,
        severity: Severity,
    ) -> bool:
        """Check if this notification was recently sent (dedup)."""
        key = f"{coordinator_id}:{title}:{location or ''}"
        window = DEDUP_WINDOWS.get(severity, NM_DEDUP_MEDIUM)
        now = dt_util.utcnow().timestamp()

        last_sent = self._dedup_cache.get(key, 0.0)
        if now - last_sent < window:
            return True

        self._dedup_cache[key] = now

        # Prune old entries
        cutoff = now - max(DEDUP_WINDOWS.values())
        self._dedup_cache = {
            k: v for k, v in self._dedup_cache.items() if v > cutoff
        }
        return False

    # =========================================================================
    # Channel qualification
    # =========================================================================

    def _channel_qualifies(self, channel: str, severity: Severity) -> bool:
        """Check if a channel should fire for a given severity."""
        channel_config = {
            "pushover": (CONF_NM_PUSHOVER_ENABLED, CONF_NM_PUSHOVER_SEVERITY, DEFAULT_NM_PUSHOVER_SEVERITY),
            "companion": (CONF_NM_COMPANION_ENABLED, CONF_NM_COMPANION_SEVERITY, DEFAULT_NM_COMPANION_SEVERITY),
            "whatsapp": (CONF_NM_WHATSAPP_ENABLED, CONF_NM_WHATSAPP_SEVERITY, DEFAULT_NM_WHATSAPP_SEVERITY),
            "tts": (CONF_NM_TTS_ENABLED, CONF_NM_TTS_SEVERITY, DEFAULT_NM_TTS_SEVERITY),
            "lights": (CONF_NM_LIGHTS_ENABLED, CONF_NM_LIGHTS_SEVERITY, DEFAULT_NM_LIGHTS_SEVERITY),
        }

        conf = channel_config.get(channel)
        if not conf:
            return False

        enabled_key, severity_key, default_severity = conf
        if not self._config.get(enabled_key, False):
            return False

        threshold_str = self._config.get(severity_key, default_severity)
        threshold = SEVERITY_MAP.get(threshold_str, Severity.MEDIUM)
        return severity >= threshold

    # =========================================================================
    # Digest
    # =========================================================================

    def _setup_digest_timers(self) -> None:
        """Set up daily digest delivery timers for each person."""
        persons = self._config.get(CONF_NM_PERSONS, [])
        for person_cfg in persons:
            delivery_pref = person_cfg.get(CONF_NM_PERSON_DELIVERY_PREF, NM_DELIVERY_IMMEDIATE)
            if delivery_pref != NM_DELIVERY_DIGEST:
                continue

            person_id = person_cfg.get(CONF_NM_PERSON_ENTITY, "")

            # Morning digest
            morning_time = person_cfg.get(CONF_NM_PERSON_DIGEST_MORNING, "08:00")
            try:
                hour, minute = map(int, morning_time.split(":"))
                unsub = async_track_time_change(
                    self.hass,
                    lambda now, pid=person_id, pcfg=person_cfg: self.hass.async_create_task(
                        self._fire_digest(pid, pcfg)
                    ),
                    hour=hour,
                    minute=minute,
                    second=0,
                )
                self._digest_unsubs.append(unsub)
            except (ValueError, AttributeError):
                _LOGGER.warning("Invalid morning digest time: %s", morning_time)

            # Evening digest (optional)
            if person_cfg.get(CONF_NM_PERSON_DIGEST_EVENING_ENABLED, False):
                evening_time = person_cfg.get(CONF_NM_PERSON_DIGEST_EVENING, "18:00")
                try:
                    hour, minute = map(int, evening_time.split(":"))
                    unsub = async_track_time_change(
                        self.hass,
                        lambda now, pid=person_id, pcfg=person_cfg: self.hass.async_create_task(
                            self._fire_digest(pid, pcfg)
                        ),
                        hour=hour,
                        minute=minute,
                        second=0,
                    )
                    self._digest_unsubs.append(unsub)
                except (ValueError, AttributeError):
                    _LOGGER.warning("Invalid evening digest time: %s", evening_time)

    async def _fire_digest(self, person_id: str, person_cfg: dict[str, Any]) -> None:
        """Deliver the daily digest for a person."""
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if not database:
            return

        pending = await database.get_pending_digest(person_id)
        if not pending:
            return

        digest_message = self._format_digest(pending)

        # Send via lowest-severity qualifying channel
        sent = False
        if self._config.get(CONF_NM_PUSHOVER_ENABLED):
            key = person_cfg.get(CONF_NM_PERSON_PUSHOVER_KEY, "")
            if key:
                await self._send_pushover("URA Daily Summary", digest_message, Severity.LOW, key)
                sent = True

        if not sent and self._config.get(CONF_NM_COMPANION_ENABLED):
            svc = person_cfg.get(CONF_NM_PERSON_COMPANION_SERVICE, "")
            if svc:
                await self._send_companion("URA Daily Summary", digest_message, Severity.LOW, svc)
                sent = True

        if not sent and self._config.get(CONF_NM_WHATSAPP_ENABLED):
            phone = person_cfg.get(CONF_NM_PERSON_WHATSAPP_PHONE, "")
            if phone:
                await self._send_whatsapp("URA Daily Summary", digest_message, phone)
                sent = True

        if sent:
            await database.mark_digest_delivered(person_id)
            _LOGGER.info("Digest delivered to %s (%d items)", person_id, len(pending))

    def _format_digest(self, items: list[dict]) -> str:
        """Format pending digest items into a readable summary."""
        today = dt_util.now().strftime("%B %d, %Y")
        lines = [f"URA Daily Summary ({today})", ""]

        # Group by coordinator
        by_coordinator: dict[str, list[dict]] = defaultdict(list)
        for item in items:
            by_coordinator[item.get("coordinator_id", "unknown")].append(item)

        for coord_id, coord_items in by_coordinator.items():
            lines.append(f"{coord_id.title()} ({len(coord_items)} events):")

            # Group by title+location and count
            counts: dict[str, int] = defaultdict(int)
            for item in sorted(coord_items, key=lambda x: x.get("severity", ""), reverse=True):
                key = f"{item.get('severity', '?')}|{item.get('title', '')} — {item.get('location', '')}"
                counts[key] += 1

            for key, count in counts.items():
                sev, msg = key.split("|", 1)
                icon = "!!" if sev in ("HIGH", "CRITICAL") else "!"
                prefix = f"  {icon} {count}x " if count > 1 else f"  {icon} "
                lines.append(f"{prefix}{msg}")
            lines.append("")

        return "\n".join(lines)

    # =========================================================================
    # Recovery from DB
    # =========================================================================

    async def _recover_state_from_db(self) -> None:
        """Recover NM state from database after restart."""
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if not database:
            return

        # Refresh today count
        await self.async_refresh_today_count()

        # Load last notification
        last = await database.get_last_notification()
        if last:
            self._last_notification = {
                "severity": last.get("severity", ""),
                "coordinator": last.get("coordinator_id", ""),
                "title": last.get("title", ""),
                "message": last.get("message", ""),
                "hazard_type": last.get("hazard_type"),
                "location": last.get("location"),
                "channels": [last.get("channel", "")],
                "timestamp": last.get("timestamp", ""),
            }

        # Check for unacked CRITICAL — resume repeating
        active = await database.get_active_critical()
        if active:
            _LOGGER.warning("Recovering unacknowledged CRITICAL alert from DB")
            self._alert_state = AlertState.REPEATING
            self._active_alert_data = {
                "coordinator_id": active.get("coordinator_id", ""),
                "severity": "CRITICAL",
                "title": active.get("title", ""),
                "message": active.get("message", ""),
                "hazard_type": active.get("hazard_type"),
                "location": active.get("location"),
            }
            self._schedule_repeat()
            async_dispatcher_send(self.hass, SIGNAL_NM_ALERT_STATE_CHANGED)
            return

        # Check for active cooldown — resume timer
        cooldown = await database.get_active_cooldown()
        if cooldown:
            expires_str = cooldown.get("cooldown_expires", "")
            try:
                expires = datetime.fromisoformat(expires_str)
                now = dt_util.utcnow()
                if hasattr(expires, "tzinfo") and expires.tzinfo is None:
                    from datetime import timezone
                    expires = expires.replace(tzinfo=timezone.utc)
                remaining = (expires - now).total_seconds()
                if remaining > 0:
                    _LOGGER.info("Recovering cooldown from DB (%d seconds remaining)", remaining)
                    self._alert_state = AlertState.COOLDOWN
                    self._cooldown_remaining = int(remaining)
                    self._active_alert_data = {
                        "coordinator_id": cooldown.get("coordinator_id", ""),
                        "severity": "CRITICAL",
                        "title": cooldown.get("title", ""),
                        "message": cooldown.get("message", ""),
                        "hazard_type": cooldown.get("hazard_type"),
                        "location": cooldown.get("location"),
                    }
                    self._cooldown_hazard_type = cooldown.get("hazard_type")
                    self._cooldown_location = cooldown.get("location")
                    self._cooldown_unsub = async_call_later(
                        self.hass, remaining, self._cooldown_expired
                    )
                    self._countdown_task = self.hass.async_create_task(self._countdown_tick())
                    async_dispatcher_send(self.hass, SIGNAL_NM_ALERT_STATE_CHANGED)
            except (ValueError, TypeError) as e:
                _LOGGER.warning("Failed to parse cooldown expiry: %s", e)

    # =========================================================================
    # Helpers
    # =========================================================================

    async def async_refresh_today_count(self) -> None:
        """Refresh the today notification count from DB."""
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database:
            today = await database.get_notifications_today()
            self._notifications_today_count = len(today)

    async def async_test_notification(
        self,
        severity: str = "MEDIUM",
        channel: str | None = None,
    ) -> None:
        """Send a test notification to verify channel configuration."""
        sev = SEVERITY_MAP.get(severity.upper(), Severity.MEDIUM)
        title = "URA Test Notification"
        message = f"This is a test notification at {severity} severity."

        if channel:
            # Send to a specific channel only
            _LOGGER.info("Test notification to channel=%s severity=%s", channel, severity)
            persons = self._config.get(CONF_NM_PERSONS, [])
            if channel == "pushover":
                for p in persons:
                    key = p.get(CONF_NM_PERSON_PUSHOVER_KEY, "")
                    if key:
                        await self._send_pushover(title, message, sev, key)
            elif channel == "companion":
                for p in persons:
                    svc = p.get(CONF_NM_PERSON_COMPANION_SERVICE, "")
                    if svc:
                        await self._send_companion(title, message, sev, svc)
            elif channel == "whatsapp":
                for p in persons:
                    phone = p.get(CONF_NM_PERSON_WHATSAPP_PHONE, "")
                    if phone:
                        await self._send_whatsapp(title, message, phone)
            elif channel == "tts":
                await self._send_tts(title, message)
            elif channel == "lights":
                await self._trigger_alert_lights("warning", sev)
            self._last_notification = {
                "severity": severity, "coordinator": "test", "title": title,
                "message": message, "hazard_type": None, "location": None,
                "channels": [channel], "timestamp": dt_util.utcnow().isoformat(),
            }
            self._notifications_today_count += 1
            async_dispatcher_send(self.hass, SIGNAL_NM_ENTITIES_UPDATE)
        else:
            await self.async_notify(
                coordinator_id="test",
                severity=sev,
                title=title,
                message=message,
                hazard_type=None,
                location=None,
            )

    def _update_channel_health(self, channel: str, success: bool) -> None:
        """Update channel health tracking."""
        self._send_attempts += 1
        if success:
            self._send_successes += 1
            if channel in self._notifications_by_channel:
                self._notifications_by_channel[channel] += 1
        else:
            self._send_failures += 1

        health = self._channel_health.get(channel)
        if not health:
            return
        if success:
            health["status"] = "ok"
            health["last_success"] = dt_util.utcnow().isoformat()
            health["failures"] = 0
        else:
            health["failures"] = health.get("failures", 0) + 1
            if health["failures"] >= 3:
                health["status"] = "degraded"

    def _update_hourly_count(self) -> None:
        """Track notification count for the current hour (anomaly detection)."""
        now = dt_util.now()
        hour_idx = now.hour
        if hour_idx != self._current_hour_idx:
            # New hour — reset the slot
            self._current_hour_idx = hour_idx
            self._hourly_counts[hour_idx] = 0
        self._hourly_counts[hour_idx] += 1

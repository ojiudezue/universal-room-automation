"""Notification Manager — centralized notification delivery and inbound handling.

Handles 6 channel types (Pushover, Companion App, WhatsApp, iMessage, TTS, Alert Lights)
with severity-based routing, per-person config, ack/cooldown/re-fire for
CRITICAL alerts, quiet hours, daily digest mode, and SQLite persistence.

v3.6.29: Initial implementation (C4a).
v3.9.7: C4b — Inbound message parsing, safe word ack, response dict, TTS ack.
v3.9.8: C4b+ — BlueBubbles/iMessage channel, Pushover device targeting fix.
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

from homeassistant.components import webhook
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
    CONF_NM_IMESSAGE_ENABLED,
    CONF_NM_IMESSAGE_SEVERITY,
    CONF_NM_LIGHTS_ENABLED,
    CONF_NM_LIGHTS_SEVERITY,
    CONF_NM_PERSONS,
    CONF_NM_PERSON_COMPANION_SERVICE,
    CONF_NM_PERSON_DELIVERY_PREF,
    CONF_NM_PERSON_DIGEST_EVENING,
    CONF_NM_PERSON_DIGEST_EVENING_ENABLED,
    CONF_NM_PERSON_DIGEST_MORNING,
    CONF_NM_PERSON_ENTITY,
    CONF_NM_PERSON_IMESSAGE_HANDLE,
    CONF_NM_PERSON_PUSHOVER_DEVICE,
    CONF_NM_PERSON_PUSHOVER_KEY,
    CONF_NM_PERSON_WHATSAPP_PHONE,
    CONF_NM_PUSHOVER_ENABLED,
    CONF_NM_PUSHOVER_SERVICE,
    CONF_NM_PUSHOVER_SEVERITY,
    CONF_NM_QUIET_MANUAL_END,
    CONF_NM_QUIET_MANUAL_START,
    CONF_NM_QUIET_USE_HOUSE_STATE,
    CONF_NM_SAFE_WORD,
    CONF_NM_SILENCE_DURATION,
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
    DEFAULT_NM_IMESSAGE_SEVERITY,
    DEFAULT_NM_LIGHTS_SEVERITY,
    DEFAULT_NM_PUSHOVER_SEVERITY,
    DEFAULT_NM_SILENCE_DURATION,
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
    WEBHOOK_BB_ID,
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


# =========================================================================
# C4b: Response dictionary for inbound message parsing
# =========================================================================

RESPONSE_COMMANDS: dict[str, str] = {
    # Acknowledge
    "1": "ack", "ack": "ack", "ok": "ack", "acknowledge": "ack", "a": "ack",
    # Status
    "2": "status", "status": "status", "s": "status", "info": "status",
    # Silence
    "3": "silence", "stop": "silence", "silence": "silence",
    "mute": "silence", "quiet": "silence",
    # Help
    "help": "help", "?": "help", "h": "help",
}

RESPONSE_DICT_TEXT = "Reply: 1=Ack  2=Status  3=Silence"
CRITICAL_RESPONSE_TEXT = (
    "Reply with your safe word to acknowledge.\n"
    "Reply: 2=Status  3=Silence repeats (30 min)"
)
WEBHOOK_ID = f"{DOMAIN}_pushover_reply"


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
        self._messaging_suppressed = False
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
            "imessage": {"status": "ok", "last_success": None, "failures": 0},
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
            "pushover": 0, "companion": 0, "whatsapp": 0, "imessage": 0, "tts": 0, "lights": 0,
        }
        # Rolling window for anomaly detection (hourly counts, last 24h)
        self._hourly_counts: list[int] = [0] * 24
        self._current_hour_idx: int = -1

        # C4b: Inbound handling
        self._wa_unsub: CALLBACK_TYPE | None = None
        self._webhook_unsub: bool = False
        self._bb_webhook_registered: bool = False
        self._silence_until: datetime | None = None
        self._inbound_today_count: int = 0
        self._inbound_by_channel: dict[str, int] = {
            "whatsapp": 0, "pushover": 0, "companion": 0, "imessage": 0,
        }
        self._inbound_by_command: dict[str, int] = {
            "ack": 0, "status": 0, "silence": 0, "help": 0, "safe_word": 0, "unknown": 0,
        }

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
    def messaging_suppressed(self) -> bool:
        """Return whether outbound messaging is suppressed."""
        return self._messaging_suppressed

    async def async_suppress_messaging(self) -> None:
        """Kill switch — suppress all outbound messaging and stop active alerts."""
        self._messaging_suppressed = True
        _LOGGER.warning("Messaging suppressed — all outbound notifications halted")
        # Auto-acknowledge any active alert to stop repeats
        if self._alert_state in (AlertState.ALERTING, AlertState.REPEATING):
            if self._repeat_unsub:
                self._repeat_unsub()
                self._repeat_unsub = None
            self._alert_state = AlertState.IDLE
            self._active_alert_data = None
            self._cooldown_remaining = 0
            _LOGGER.info("Active alert cancelled by messaging kill switch")
        # Clear silence timer too
        self._silence_until = None

    async def async_resume_messaging(self) -> None:
        """Resume outbound messaging."""
        self._messaging_suppressed = False
        _LOGGER.info("Messaging resumed — outbound notifications re-enabled")

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
            "inbound_today": self._inbound_today_count,
            "messaging_suppressed": self._messaging_suppressed,
            "safe_word_configured": self.safe_word_configured,
            "inbound_channels_active": [
                ch for ch, enabled in [
                    ("whatsapp", self._wa_unsub is not None),
                    ("pushover", self._webhook_unsub),
                    ("companion", self._action_unsub is not None),
                    ("imessage", self._bb_webhook_registered),
                ] if enabled
            ],
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

    @property
    def inbound_today(self) -> int:
        """Return count of inbound messages today."""
        return self._inbound_today_count

    @property
    def inbound_by_channel(self) -> dict[str, int]:
        """Return inbound message breakdown by channel."""
        return dict(self._inbound_by_channel)

    @property
    def inbound_by_command(self) -> dict[str, int]:
        """Return inbound message breakdown by parsed command."""
        return dict(self._inbound_by_command)

    @property
    def safe_word_configured(self) -> bool:
        """Return whether a safe word is configured."""
        word = self._config.get(CONF_NM_SAFE_WORD, "")
        return bool(word and len(word.strip()) >= 4)

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
            pruned_inbound = await database.prune_inbound_log(RETENTION_NOTIFICATION_LOG)
            if pruned_inbound:
                _LOGGER.info("Pruned %d old inbound log entries", pruned_inbound)

        # Recover state from DB
        await self._recover_state_from_db()

        # Set up digest timers
        self._setup_digest_timers()

        # Subscribe to companion app action events
        self._action_unsub = self.hass.bus.async_listen(
            "mobile_app_notification_action", self._handle_companion_action
        )

        # C4b: Subscribe to WhatsApp inbound events
        if self._config.get(CONF_NM_WHATSAPP_ENABLED, False):
            self._wa_unsub = self.hass.bus.async_listen(
                "whatsapp_message_received", self._handle_whatsapp_reply
            )

        # C4b: Register Pushover reply webhook
        if self._config.get(CONF_NM_PUSHOVER_ENABLED, False):
            try:
                webhook.async_register(
                    self.hass, DOMAIN, "NM Pushover Reply",
                    WEBHOOK_ID, self._handle_pushover_webhook,
                )
                self._webhook_unsub = True
            except Exception as e:
                _LOGGER.warning("Failed to register Pushover webhook: %s", e)

        # C4b+: Register BlueBubbles inbound webhook
        if self._config.get(CONF_NM_IMESSAGE_ENABLED, False):
            try:
                webhook.async_register(
                    self.hass, DOMAIN, "NM BlueBubbles Reply",
                    WEBHOOK_BB_ID, self._handle_bb_webhook,
                )
                self._bb_webhook_registered = True
            except Exception as e:
                _LOGGER.warning("Failed to register BlueBubbles webhook: %s", e)

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

        # Cancel inbound listeners (C4b)
        if self._wa_unsub:
            self._wa_unsub()
            self._wa_unsub = None
        if self._webhook_unsub:
            try:
                webhook.async_unregister(self.hass, WEBHOOK_ID)
            except Exception:
                pass
            self._webhook_unsub = False
        if self._bb_webhook_registered:
            try:
                webhook.async_unregister(self.hass, WEBHOOK_BB_ID)
            except Exception:
                pass
            self._bb_webhook_registered = False

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

        # v3.15.3: Messaging kill switch — block all outbound
        if self._messaging_suppressed:
            _LOGGER.debug("Notification suppressed by messaging kill switch: %s", title)
            return

        # v3.15.3: Live severity re-check — re-read config from config entry
        # so OptionsFlow changes take effect without restart
        self._refresh_config()

        # Quiet hours check (CRITICAL bypasses)
        if severity != Severity.CRITICAL and self._is_quiet_hours():
            _LOGGER.debug("Notification suppressed during quiet hours: %s", title)
            self._quiet_suppressions += 1
            return

        # C4b: Silence check — suppress non-CRITICAL when silenced
        if (
            severity != Severity.CRITICAL
            and self._silence_until
            and dt_util.utcnow() < self._silence_until
        ):
            _LOGGER.debug("Notification suppressed by silence: %s", title)
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

        # C4b: Append response dict to message for text channels
        if severity == Severity.CRITICAL:
            message_with_dict = f"{message}\n\n{CRITICAL_RESPONSE_TEXT}"
        else:
            message_with_dict = f"{message}\n\n{RESPONSE_DICT_TEXT}"

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
                pushover_device = person_cfg.get(CONF_NM_PERSON_PUSHOVER_DEVICE, "")
                if pushover_key:
                    if effective_pref == NM_DELIVERY_IMMEDIATE:
                        await self._send_pushover(title, message_with_dict, severity, pushover_key, pushover_device)
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
                        await self._send_whatsapp(title, message_with_dict, phone)
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

            # iMessage (BlueBubbles)
            if self._channel_qualifies("imessage", severity):
                imessage_handle = person_cfg.get(CONF_NM_PERSON_IMESSAGE_HANDLE, "")
                if imessage_handle:
                    if effective_pref == NM_DELIVERY_IMMEDIATE:
                        await self._send_imessage(title, message_with_dict, imessage_handle)
                        channels_fired.append("imessage")
                        if database:
                            await database.log_notification(
                                coordinator_id, severity_str, title, message,
                                hazard_type, location, person_id, "imessage", 1,
                            )
                    elif effective_pref == NM_DELIVERY_DIGEST:
                        if database:
                            await database.log_notification(
                                coordinator_id, severity_str, title, message,
                                hazard_type, location, person_id, "imessage", 0,
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
        device: str = "",
    ) -> None:
        """Send notification via Pushover."""
        service_name = self._config.get(CONF_NM_PUSHOVER_SERVICE, "notify.pushover")
        try:
            domain, service = service_name.split(".", 1)
            data: dict[str, Any] = {
                "title": title,
                "message": message,
            }
            # Target specific device if configured, otherwise sends to all
            if device:
                data["target"] = device
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
                            "action": "ACKNOWLEDGE_URA_CRITICAL",
                            "title": "Acknowledge (safe word)",
                            "behavior": "textInput",
                            "textInputPlaceholder": "Enter safe word",
                            "textInputButtonTitle": "Submit",
                        },
                        {"action": "STATUS_URA", "title": "Status"},
                        {"action": "SILENCE_URA", "title": "Silence 30min"},
                    ],
                    "push": {"sound": {"name": "default", "critical": 1, "volume": 1.0}},
                }
            else:
                data["data"] = {
                    "actions": [
                        {"action": "ACKNOWLEDGE_URA", "title": "Acknowledge"},
                        {"action": "STATUS_URA", "title": "Status"},
                        {"action": "SILENCE_URA", "title": "Silence 30min"},
                    ],
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
                {"number": phone, "message": f"*{title}*\n{message}"},
                blocking=True,
            )
            self._update_channel_health("whatsapp", True)
        except Exception as e:
            _LOGGER.error("WhatsApp send failed: %s", e)
            self._update_channel_health("whatsapp", False)

    async def _send_imessage(self, title: str, message: str, handle: str) -> None:
        """Send notification via BlueBubbles (iMessage)."""
        try:
            await self.hass.services.async_call(
                "bluebubbles", "send_message",
                {"addresses": handle, "message": f"{title}\n{message}"},
                blocking=True,
            )
            self._update_channel_health("imessage", True)
        except Exception as e:
            _LOGGER.error("iMessage send via BlueBubbles failed: %s", e)
            self._update_channel_health("imessage", False)

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
                    "color_temp_kelvin": state.attributes.get("color_temp_kelvin"),
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
                    elif orig.get("color_temp_kelvin"):
                        svc_data["color_temp_kelvin"] = orig["color_temp_kelvin"]
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
        if not self.enabled or self._messaging_suppressed:
            return
        if self._alert_state != AlertState.REPEATING or not self._active_alert_data:
            return

        # v3.15.3: Re-read config so severity changes take effect on repeats
        self._refresh_config()

        data = self._active_alert_data
        _LOGGER.info("Repeating CRITICAL alert: %s", data.get("title"))

        # Re-send to all qualifying channels
        persons = self._config.get(CONF_NM_PERSONS, [])
        for person_cfg in persons:
            if self._channel_qualifies("pushover", Severity.CRITICAL):
                key = person_cfg.get(CONF_NM_PERSON_PUSHOVER_KEY, "")
                device = person_cfg.get(CONF_NM_PERSON_PUSHOVER_DEVICE, "")
                if key:
                    await self._send_pushover(
                        data["title"], data["message"], Severity.CRITICAL, key, device
                    )
            if self._channel_qualifies("companion", Severity.CRITICAL):
                svc = person_cfg.get(CONF_NM_PERSON_COMPANION_SERVICE, "")
                if svc:
                    await self._send_companion(
                        data["title"], data["message"], Severity.CRITICAL, svc,
                        is_critical=True,
                    )
            if self._channel_qualifies("whatsapp", Severity.CRITICAL):
                phone = person_cfg.get(CONF_NM_PERSON_WHATSAPP_PHONE, "")
                if phone:
                    await self._send_whatsapp(data["title"], data["message"], phone)
            if self._channel_qualifies("imessage", Severity.CRITICAL):
                handle = person_cfg.get(CONF_NM_PERSON_IMESSAGE_HANDLE, "")
                if handle:
                    await self._send_imessage(data["title"], data["message"], handle)

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
    # C4b: Inbound message handling
    # =========================================================================

    @callback
    def _handle_companion_action(self, event: Event) -> None:
        """Handle companion app notification action button press."""
        action = event.data.get("action", "")
        if action == "ACKNOWLEDGE_URA":
            self.hass.async_create_task(self.async_acknowledge())
        elif action == "STATUS_URA":
            self.hass.async_create_task(
                self._process_inbound_reply(None, "companion", "status")
            )
        elif action == "SILENCE_URA":
            self.hass.async_create_task(
                self._process_inbound_reply(None, "companion", "silence")
            )
        elif action == "ACKNOWLEDGE_URA_CRITICAL":
            # Text input action — the reply text is in event.data
            text = event.data.get("reply_text", event.data.get("textInput", ""))
            if text:
                self.hass.async_create_task(
                    self._process_inbound_reply(None, "companion", text)
                )

    @callback
    def _handle_whatsapp_reply(self, event: Event) -> None:
        """Handle inbound WhatsApp message via ha-wa-bridge."""
        phone = event.data.get("phone", "")
        message = event.data.get("message", "")
        if not message:
            return
        person_id = self._match_person_by_phone(phone)
        if person_id is None:
            return
        self.hass.async_create_task(
            self._process_inbound_reply(person_id, "whatsapp", message)
        )

    async def _handle_pushover_webhook(
        self, hass: HomeAssistant, webhook_id: str, request
    ) -> None:
        """Handle Pushover reply webhook POST."""
        try:
            data = await request.json()
        except Exception:
            try:
                data = await request.post()
            except Exception:
                return
        user_key = data.get("user", "")
        message = data.get("message", "")
        if not message:
            return
        person_id = self._match_person_by_pushover_key(user_key)
        if person_id is None:
            return
        await self._process_inbound_reply(person_id, "pushover", message)

    async def _handle_bb_webhook(
        self, hass: HomeAssistant, webhook_id: str, request,
    ) -> None:
        """Handle BlueBubbles new-message webhook POST."""
        try:
            data = await request.json()
        except Exception:
            return

        # Only process incoming new-message events
        event_type = data.get("type", "")
        if event_type != "new-message":
            return

        msg_data = data.get("data", {})

        # Skip messages sent by us
        if msg_data.get("isFromMe", False):
            return

        text = msg_data.get("text", "")
        if not text:
            return

        # Extract sender handle (phone or email)
        handle_obj = msg_data.get("handle", {})
        sender = handle_obj.get("address", "") if isinstance(handle_obj, dict) else ""

        person_id = self._match_person_by_imessage_handle(sender)

        # v3.15.3: Only process messages from known persons — BB webhook
        # fires for ALL incoming iMessages, not just NM reply threads.
        # Unknown senders are silently ignored to prevent spam loops.
        if person_id is None:
            return

        await self._process_inbound_reply(person_id, "imessage", text)

    def _match_person_by_phone(self, phone: str) -> str | None:
        """Match a phone number to a person entity ID."""
        persons = self._config.get(CONF_NM_PERSONS, [])
        for p in persons:
            p_phone = p.get(CONF_NM_PERSON_WHATSAPP_PHONE, "")
            if p_phone and phone.endswith(p_phone[-10:]):
                return p.get(CONF_NM_PERSON_ENTITY)
        return None

    def _match_person_by_pushover_key(self, user_key: str) -> str | None:
        """Match a Pushover user key to a person entity ID."""
        persons = self._config.get(CONF_NM_PERSONS, [])
        for p in persons:
            p_key = p.get(CONF_NM_PERSON_PUSHOVER_KEY, "")
            if p_key and p_key == user_key:
                return p.get(CONF_NM_PERSON_ENTITY)
        return None

    def _match_person_by_imessage_handle(self, handle: str) -> str | None:
        """Match an iMessage handle (phone or email) to a person entity ID."""
        persons = self._config.get(CONF_NM_PERSONS, [])
        normalized = handle.strip().lower()
        for p in persons:
            p_handle = p.get(CONF_NM_PERSON_IMESSAGE_HANDLE, "").strip().lower()
            if not p_handle:
                continue
            # Email match: exact case-insensitive
            if "@" in p_handle and p_handle == normalized:
                return p.get(CONF_NM_PERSON_ENTITY)
            # Phone match: last 10 digits (same logic as WhatsApp)
            if "@" not in p_handle and normalized.endswith(p_handle[-10:]):
                return p.get(CONF_NM_PERSON_ENTITY)
        return None

    async def _process_inbound_reply(
        self,
        person_id: str | None,
        channel: str,
        raw_text: str,
    ) -> str:
        """Process an inbound text reply. Returns response text."""
        text = raw_text.strip().lower()
        database = self.hass.data.get(DOMAIN, {}).get("database")

        # v3.15.3: Kill switch blocks replies too
        if self._messaging_suppressed:
            return ""

        # Track inbound
        self._inbound_today_count += 1
        if channel in self._inbound_by_channel:
            self._inbound_by_channel[channel] += 1

        # Parse command
        command = RESPONSE_COMMANDS.get(text)
        safe_word = self._config.get(CONF_NM_SAFE_WORD, "")
        is_safe_word = (
            safe_word
            and len(safe_word.strip()) >= 4
            and text == safe_word.strip().lower()
        )

        # Check if currently silenced
        if self._silence_until and dt_util.utcnow() < self._silence_until:
            if command not in ("status", "help") and not is_safe_word:
                response = "Alerts silenced. Will resume at {}.".format(
                    self._silence_until.strftime("%H:%M")
                )
                await self._log_and_reply(
                    database, person_id, channel, raw_text,
                    "silenced", response, success=True,
                )
                return response

        has_active_alert = self._alert_state in (
            AlertState.ALERTING, AlertState.REPEATING
        )
        is_critical = (
            has_active_alert
            and self._active_alert_data
            and self._active_alert_data.get("severity") == "CRITICAL"
        )

        # Safe word match
        if is_safe_word:
            self._inbound_by_command["safe_word"] += 1
            if is_critical:
                person_name = self._get_person_name(person_id)
                hazard_type = self._active_alert_data.get("hazard_type", "")
                location = self._active_alert_data.get("location", "")
                await self.async_acknowledge()
                await self._announce_ack(person_name, hazard_type, location)
                response = f"CRITICAL alert acknowledged by {person_name}."
            elif has_active_alert:
                await self.async_acknowledge()
                response = "Alert acknowledged."
            else:
                response = "No active alert to acknowledge."
            await self._log_and_reply(
                database, person_id, channel, "[safe_word]",
                "safe_word", response, success=is_critical or has_active_alert,
            )
            return response

        if command == "ack":
            self._inbound_by_command["ack"] += 1
            if is_critical:
                response = "CRITICAL alert requires safe word. Reply with your safe word to acknowledge."
            elif has_active_alert:
                await self.async_acknowledge()
                response = "Alert acknowledged."
            else:
                response = "No active alerts."
            await self._log_and_reply(
                database, person_id, channel, raw_text,
                "ack", response, success=has_active_alert and not is_critical,
            )
            return response

        if command == "status":
            self._inbound_by_command["status"] += 1
            response = self._build_status_response()
            await self._log_and_reply(
                database, person_id, channel, raw_text,
                "status", response, success=True,
            )
            return response

        if command == "silence":
            self._inbound_by_command["silence"] += 1
            silence_mins = int(
                self._config.get(CONF_NM_SILENCE_DURATION, DEFAULT_NM_SILENCE_DURATION)
            )
            self._silence_until = dt_util.utcnow() + timedelta(minutes=silence_mins)
            response = f"Non-CRITICAL alerts silenced for {silence_mins} minutes."
            await self._log_and_reply(
                database, person_id, channel, raw_text,
                "silence", response, success=True,
            )
            return response

        if command == "help":
            self._inbound_by_command["help"] += 1
            response = RESPONSE_DICT_TEXT
            if is_critical:
                response = CRITICAL_RESPONSE_TEXT
            await self._log_and_reply(
                database, person_id, channel, raw_text,
                "help", response, success=True,
            )
            return response

        # Unrecognized — only reply when there's an active alert or recent
        # notification context. Otherwise silently ignore to prevent spam from
        # random texts that happen to come from known persons.
        has_context = (
            self._alert_state != AlertState.IDLE
            or self._notifications_today_count > 0
        )
        if not has_context:
            _LOGGER.debug("Ignoring unrecognized inbound '%s' — no alert context", raw_text)
            return ""

        self._inbound_by_command["unknown"] += 1
        response = f"Unknown command. {RESPONSE_DICT_TEXT}"
        await self._log_and_reply(
            database, person_id, channel, raw_text,
            "unknown", response, success=False,
        )
        return response

    def _build_status_response(self) -> str:
        """Build a status response summarizing current alert state."""
        if self._alert_state == AlertState.IDLE:
            return "URA Alert Status: No active alerts. All clear."

        lines = ["URA Alert Status:"]
        if self._active_alert_data:
            data = self._active_alert_data
            lines.append(
                f"- Active: {data.get('hazard_type', 'unknown')} "
                f"in {data.get('location', 'unknown')} "
                f"({data.get('severity', '?')})"
            )
        lines.append(f"- State: {self._alert_state.value.upper()}")
        if self._alert_state == AlertState.COOLDOWN:
            mins = self._cooldown_remaining // 60
            lines.append(f"- Cooldown: {mins}min remaining")
        if self._silence_until and dt_util.utcnow() < self._silence_until:
            lines.append(
                f"- Silenced until {self._silence_until.strftime('%H:%M')}"
            )
        return "\n".join(lines)

    async def _announce_ack(
        self, person_name: str, hazard_type: str, location: str
    ) -> None:
        """Announce CRITICAL alert acknowledgment via TTS."""
        speakers = self._config.get(CONF_NM_TTS_SPEAKERS, [])
        if not speakers:
            return
        message = f"{hazard_type} alert acknowledged by {person_name}"
        if location:
            message += f" in {location}"
        try:
            for speaker in speakers:
                await self.hass.services.async_call(
                    "tts", "speak",
                    {"media_player_entity_id": speaker, "message": message},
                    blocking=False,
                )
        except Exception as e:
            _LOGGER.error("TTS ack announcement failed: %s", e)

    async def _log_and_reply(
        self,
        database,
        person_id: str | None,
        channel: str,
        raw_text: str,
        parsed_command: str,
        response: str,
        success: bool,
    ) -> None:
        """Log inbound to DB, send reply, and update sensors."""
        alert_id = None
        if self._active_alert_data and database:
            active = await database.get_active_critical()
            if active:
                alert_id = active.get("id")

        if database:
            await database.log_inbound(
                person_id, channel, raw_text,
                parsed_command, response, alert_id, success,
            )

        # Send reply back via originating channel
        if person_id:
            await self._send_reply(person_id, channel, response)

        async_dispatcher_send(self.hass, SIGNAL_NM_ENTITIES_UPDATE)

    async def _send_reply(
        self, person_id: str, channel: str, message: str
    ) -> None:
        """Send a text response back via the originating channel."""
        persons = self._config.get(CONF_NM_PERSONS, [])
        person_cfg = next(
            (p for p in persons if p.get(CONF_NM_PERSON_ENTITY) == person_id),
            None,
        )
        if not person_cfg:
            return

        if channel == "whatsapp":
            phone = person_cfg.get(CONF_NM_PERSON_WHATSAPP_PHONE, "")
            if phone:
                await self._send_whatsapp("URA", message, phone)
        elif channel == "imessage":
            handle = person_cfg.get(CONF_NM_PERSON_IMESSAGE_HANDLE, "")
            if handle:
                await self._send_imessage("URA", message, handle)
        elif channel == "pushover":
            key = person_cfg.get(CONF_NM_PERSON_PUSHOVER_KEY, "")
            device = person_cfg.get(CONF_NM_PERSON_PUSHOVER_DEVICE, "")
            if key:
                await self._send_pushover("URA", message, Severity.LOW, key, device)
        elif channel == "companion":
            svc = person_cfg.get(CONF_NM_PERSON_COMPANION_SERVICE, "")
            if svc:
                await self._send_companion("URA", message, Severity.LOW, svc)

    def _get_person_name(self, person_id: str | None) -> str:
        """Get a display name for a person entity ID."""
        if not person_id:
            return "someone"
        state = self.hass.states.get(person_id)
        if state and state.attributes.get("friendly_name"):
            return state.attributes["friendly_name"]
        return person_id.replace("person.", "").replace("_", " ").title()

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
    # Live config refresh
    # =========================================================================

    def _refresh_config(self) -> None:
        """Re-read config from the coordinator manager config entry.

        v3.15.3: Severity threshold changes in OptionsFlow take effect immediately
        instead of requiring a full HA restart. This prevents the scenario where
        raising severity doesn't stop in-flight low-severity alerts.
        """
        from ..const import CONF_ENTRY_TYPE, ENTRY_TYPE_COORDINATOR_MANAGER
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                new_config = {**entry.data, **entry.options}
                self._config = new_config
                return

    # =========================================================================
    # Channel qualification
    # =========================================================================

    def _channel_qualifies(self, channel: str, severity: Severity) -> bool:
        """Check if a channel should fire for a given severity."""
        channel_config = {
            "pushover": (CONF_NM_PUSHOVER_ENABLED, CONF_NM_PUSHOVER_SEVERITY, DEFAULT_NM_PUSHOVER_SEVERITY),
            "companion": (CONF_NM_COMPANION_ENABLED, CONF_NM_COMPANION_SEVERITY, DEFAULT_NM_COMPANION_SEVERITY),
            "whatsapp": (CONF_NM_WHATSAPP_ENABLED, CONF_NM_WHATSAPP_SEVERITY, DEFAULT_NM_WHATSAPP_SEVERITY),
            "imessage": (CONF_NM_IMESSAGE_ENABLED, CONF_NM_IMESSAGE_SEVERITY, DEFAULT_NM_IMESSAGE_SEVERITY),
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
            device = person_cfg.get(CONF_NM_PERSON_PUSHOVER_DEVICE, "")
            if key:
                await self._send_pushover("URA Daily Summary", digest_message, Severity.LOW, key, device)
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

        if not sent and self._config.get(CONF_NM_IMESSAGE_ENABLED):
            handle = person_cfg.get(CONF_NM_PERSON_IMESSAGE_HANDLE, "")
            if handle:
                await self._send_imessage("URA Daily Summary", digest_message, handle)
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
                    device = p.get(CONF_NM_PERSON_PUSHOVER_DEVICE, "")
                    if key:
                        await self._send_pushover(title, message, sev, key, device)
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
            elif channel == "imessage":
                for p in persons:
                    handle = p.get(CONF_NM_PERSON_IMESSAGE_HANDLE, "")
                    if handle:
                        await self._send_imessage(title, message, handle)
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

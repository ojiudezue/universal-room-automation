"""Perimeter intruder alerting for Universal Room Automation v3.5.1.

PerimeterAlertManager:
  - Listens to perimeter camera state changes via async_track_state_change_event
  - During alert hours (configurable, default 23–5), if a person is detected on a
    perimeter camera and there has been no recent egress crossing (2-minute window),
    sends a notification via the configured notify service
  - Per-camera 5-minute cooldown to prevent alert storms
  - async_setup() / async_teardown() lifecycle methods

Alert hours logic:
  - If start < end  (e.g. 9–17): alert when hour in [start, end)
  - If start >= end (e.g. 23–5 overnight): alert when hour >= start OR hour < end
"""
#
# Universal Room Automation v3.5.1
# Build: 2026-02-24
# File: perimeter_alert.py
#

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_PERIMETER_CAMERAS,
    CONF_EGRESS_CAMERAS,
    CONF_PERIMETER_ALERT_HOURS_START,
    CONF_PERIMETER_ALERT_HOURS_END,
    CONF_PERIMETER_ALERT_NOTIFY_SERVICE,
    CONF_PERIMETER_ALERT_NOTIFY_TARGET,
    DEFAULT_PERIMETER_ALERT_START,
    DEFAULT_PERIMETER_ALERT_END,
    PERIMETER_ALERT_COOLDOWN_SECONDS,
    ENTRY_TYPE_INTEGRATION,
    CONF_ENTRY_TYPE,
)

_LOGGER = logging.getLogger(__name__)

# Window in seconds within which an egress crossing suppresses a perimeter alert
EGRESS_SUPPRESSION_WINDOW_SECONDS = 120  # 2 minutes


class PerimeterAlertManager:
    """Monitor perimeter cameras and send notifications for intruder detections.

    Listens for state changes on perimeter camera person-detection binary_sensors
    resolved by CameraIntegrationManager. When a person is detected:
      1. Check if current hour is within configured alert hours
      2. Check there has been no egress crossing in the last 2 minutes
      3. Check the per-camera cooldown has expired (5 minutes)
      4. Send notification via configured service
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the perimeter alert manager."""
        self.hass = hass
        # Unsubscribe callbacks for state listeners
        self._unsub_perimeter: list[Any] = []
        self._unsub_egress: list[Any] = []
        # Timestamps of last alert per camera entity_id
        self._last_alert: dict[str, datetime] = {}
        # Timestamp of most recent egress camera activation
        self._last_egress_time: datetime | None = None
        # Whether the manager is active
        self._active = False

    async def async_setup(self) -> None:
        """Set up perimeter camera listeners.

        Resolves perimeter camera entities from the integration config entry,
        then subscribes to state changes on the resolved person detection sensors.
        Returns immediately if no perimeter cameras are configured.
        """
        perimeter_sensors = self._get_person_sensors_for(CONF_PERIMETER_CAMERAS)
        egress_sensors = self._get_person_sensors_for(CONF_EGRESS_CAMERAS)

        if not perimeter_sensors:
            _LOGGER.debug(
                "PerimeterAlertManager: no perimeter cameras configured — alerting disabled"
            )
            return

        _LOGGER.info(
            "PerimeterAlertManager: monitoring %d perimeter sensor(s), "
            "%d egress sensor(s)",
            len(perimeter_sensors),
            len(egress_sensors),
        )

        # Subscribe to perimeter camera state changes
        @callback
        def _on_perimeter_state_change(event: Event) -> None:
            """Handle perimeter camera person detection state change."""
            entity_id = event.data.get("entity_id", "")
            new_state = event.data.get("new_state")
            if new_state and new_state.state == "on":
                self.hass.async_create_task(
                    self._async_handle_perimeter_trigger(entity_id)
                )

        self._unsub_perimeter.append(
            async_track_state_change_event(
                self.hass,
                perimeter_sensors,
                _on_perimeter_state_change,
            )
        )

        # Subscribe to egress camera state changes for suppression
        if egress_sensors:
            @callback
            def _on_egress_state_change(event: Event) -> None:
                """Record egress crossing time for alert suppression."""
                new_state = event.data.get("new_state")
                if new_state and new_state.state == "on":
                    self._last_egress_time = dt_util.now()
                    _LOGGER.debug(
                        "PerimeterAlertManager: egress activity recorded at %s",
                        self._last_egress_time.isoformat(),
                    )

            self._unsub_egress.append(
                async_track_state_change_event(
                    self.hass,
                    egress_sensors,
                    _on_egress_state_change,
                )
            )

        self._active = True

    async def async_teardown(self) -> None:
        """Remove all state listeners."""
        for unsub in self._unsub_perimeter:
            unsub()
        self._unsub_perimeter.clear()

        for unsub in self._unsub_egress:
            unsub()
        self._unsub_egress.clear()

        self._active = False
        _LOGGER.debug("PerimeterAlertManager: torn down")

    async def _async_handle_perimeter_trigger(self, entity_id: str) -> None:
        """Evaluate a perimeter camera person detection and send alert if warranted."""
        now = dt_util.now()

        # --- 1. Check alert hours ---
        if not self._is_in_alert_hours(now):
            _LOGGER.debug(
                "PerimeterAlertManager: person detected on %s but outside alert hours (%02d:xx)",
                entity_id,
                now.hour,
            )
            return

        # --- 2. Check egress suppression window ---
        if self._last_egress_time is not None:
            seconds_since_egress = (now - self._last_egress_time).total_seconds()
            if seconds_since_egress <= EGRESS_SUPPRESSION_WINDOW_SECONDS:
                _LOGGER.debug(
                    "PerimeterAlertManager: alert suppressed — egress crossing "
                    "%.0fs ago (within %ds window)",
                    seconds_since_egress,
                    EGRESS_SUPPRESSION_WINDOW_SECONDS,
                )
                return

        # --- 3. Check per-camera cooldown ---
        last_alert = self._last_alert.get(entity_id)
        if last_alert is not None:
            seconds_since_alert = (now - last_alert).total_seconds()
            if seconds_since_alert < PERIMETER_ALERT_COOLDOWN_SECONDS:
                _LOGGER.debug(
                    "PerimeterAlertManager: alert suppressed for %s — cooldown "
                    "(%.0fs of %ds elapsed)",
                    entity_id,
                    seconds_since_alert,
                    PERIMETER_ALERT_COOLDOWN_SECONDS,
                )
                return

        # --- 4. Send notification ---
        notify_service, notify_target = self._get_notify_config()
        if not notify_service:
            _LOGGER.warning(
                "PerimeterAlertManager: person detected on %s but no "
                "perimeter_alert_notify_service configured — skipping notification",
                entity_id,
            )
        else:
            await self._async_send_notification(
                notify_service, notify_target, entity_id, now
            )

        # Record alert time regardless of whether notification was sent
        self._last_alert[entity_id] = now
        _LOGGER.info(
            "PerimeterAlertManager: alert processed for %s at %s",
            entity_id,
            now.isoformat(),
        )

    async def _async_send_notification(
        self,
        service: str,
        target: str | None,
        camera_entity_id: str,
        timestamp: datetime,
    ) -> None:
        """Call the notification service."""
        # service format: "notify.mobile_app_john" → domain="notify", service_name="mobile_app_john"
        parts = service.split(".", 1)
        if len(parts) != 2:
            _LOGGER.error(
                "PerimeterAlertManager: invalid notify service format '%s' "
                "(expected 'domain.service')",
                service,
            )
            return

        service_domain, service_name = parts
        message = (
            f"Person detected on perimeter camera {camera_entity_id} "
            f"at {timestamp.strftime('%H:%M:%S')}."
        )
        title = "Perimeter Alert — Person Detected"

        service_data: dict[str, Any] = {
            "message": message,
            "title": title,
        }
        if target:
            service_data["target"] = target

        try:
            await self.hass.services.async_call(
                service_domain,
                service_name,
                service_data,
                blocking=False,
            )
            _LOGGER.info(
                "PerimeterAlertManager: notification sent via %s for camera %s",
                service,
                camera_entity_id,
            )
        except Exception as exc:
            _LOGGER.error(
                "PerimeterAlertManager: failed to send notification via %s: %s",
                service,
                exc,
            )

    # ------------------------------------------------------------------
    # Properties & helpers
    # ------------------------------------------------------------------

    @property
    def last_alert_time(self) -> datetime | None:
        """Return the most recent alert timestamp across all cameras, or None."""
        if not self._last_alert:
            return None
        return max(self._last_alert.values())

    @property
    def is_active(self) -> bool:
        """Return True if the manager has active listeners."""
        return self._active

    def _is_in_alert_hours(self, now: datetime) -> bool:
        """Return True if current hour falls within the configured alert window.

        Handles overnight ranges (e.g. 23–5) where start >= end.
        """
        config = self._get_integration_config()
        start = config.get(CONF_PERIMETER_ALERT_HOURS_START, DEFAULT_PERIMETER_ALERT_START)
        end = config.get(CONF_PERIMETER_ALERT_HOURS_END, DEFAULT_PERIMETER_ALERT_END)

        hour = now.hour
        if start == end:
            # Full day coverage
            return True
        if start < end:
            # Daytime window (e.g. 9–17)
            return start <= hour < end
        # Overnight window (e.g. 23–5): hour >= start OR hour < end
        return hour >= start or hour < end

    def _get_notify_config(self) -> tuple[str | None, str | None]:
        """Return (notify_service, notify_target) from integration config."""
        config = self._get_integration_config()
        service = config.get(CONF_PERIMETER_ALERT_NOTIFY_SERVICE) or None
        target = config.get(CONF_PERIMETER_ALERT_NOTIFY_TARGET) or None
        return service, target

    def _get_integration_config(self) -> dict[str, Any]:
        """Return merged data+options from the integration config entry."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
                return {**entry.data, **entry.options}
        return {}

    def _get_person_sensors_for(self, conf_key: str) -> list[str]:
        """Return resolved person-detection binary_sensor entity IDs for a camera config key.

        Uses CameraIntegrationManager if available; otherwise returns an empty list.
        """
        camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")
        if not camera_manager:
            return []

        config = self._get_integration_config()
        camera_entity_ids: list[str] = config.get(conf_key, [])
        if not camera_entity_ids:
            return []

        resolved = camera_manager.resolve_configured_cameras(camera_entity_ids)
        return [
            info.person_binary_sensor
            for info in resolved
            if info.person_binary_sensor
        ]

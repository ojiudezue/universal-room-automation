"""Perimeter intruder alerting for Universal Room Automation.

PerimeterAlertManager:
  - Listens to perimeter camera state changes via async_track_state_change_event
  - During alert hours (configurable, default 23-5), if a person is detected on a
    perimeter camera and there has been no recent egress crossing (2-minute window),
    escalates via NotificationManager.async_notify() with a house-state-derived
    severity + a Frigate/UniFi snapshot URL attachment.
  - Per-camera cooldown (PERIMETER_ALERT_COOLDOWN_SECONDS) is preserved as the
    outer rate limit; NM's dedup/bucket run on top but do NOT replace it.
  - Legacy notify_service path remains as fallback when NM is disabled/absent.
    If both are configured, NM wins and a one-shot deprecation WARN is logged.

Alert hours logic:
  - If start < end  (e.g. 9-17): alert when hour in [start, end)
  - If start >= end (e.g. 23-5 overnight): alert when hour >= start OR hour < end

Snapshot resolution (PLANNING_exterior_person_escalation D4):
  - Frigate cameras: prefer the `frigate_events` bus event's `after.id` cached
    per-camera to build `/api/frigate/notifications/<event_id>/snapshot.jpg`.
    This URL is served by the Frigate HA integration's notification proxy
    (~/ha-config/custom_components/frigate/views.py:315-424) and can be
    disabled by the operator via the Frigate integration options
    (`notification_proxy_enable`) — if disabled the URL 403s and the caller's
    channel drops the attachment; we do NOT block the alert on snapshot
    failure.
  - Fallback (UniFi Protect, or Frigate with no cached event_id): delay the
    notification by CONF_EXTERIOR_SNAPSHOT_OFFSET_S seconds (default 5) so a
    subsequently-served `entity_picture` is closer to the detection moment,
    then thread the camera's entity_picture URL.

MEASURE-BEFORE-BUILD verification notes (recorded in this cycle):

1. Frigate snapshot URL shape (verified against installed integration source at
   ~/ha-config/custom_components/frigate/views.py):
     - Multi-instance: /api/frigate/<instance_id>/notifications/<event_id>/snapshot.jpg
     - Default:       /api/frigate/notifications/<event_id>/snapshot.jpg
   Views registered as `NotificationsProxyView` (views.py:315). Permission
   check honors `notification_proxy_enable` + `notification_expiration_seconds`
   integration options; when the proxy is disabled requests are refused. This
   module uses the default (single-instance) URL form; multi-instance installs
   should set CONF_PERIMETER_ALERT_NOTIFY_SERVICE and configure a proxy on
   the URL prefix if needed. On any 403/404 the channel builder drops the
   attachment; the alert itself is never suppressed.

   The Frigate HA *integration source* does not itself call `hass.bus.async_fire`
   for detection start; the standard consumer pattern is to subscribe to the
   `frigate_events` bus event that the operator's MQTT-to-event automation (or
   an addon) publishes. We subscribe defensively — if no `frigate_events` ever
   arrives (event bus name differs, no automation wired), the Frigate branch
   silently degrades to the live-fallback path.

2. NotificationManager channel-builder snapshot threading (grep-verified in
   `notification_manager.py` below line 1318): _send_pushover uses
   `attachment_url` on Pushover; _send_companion uses `data.image`;
   _send_whatsapp uses `media_url` (best-effort passthrough); _send_imessage
   (BlueBubbles) uses `attachment`. TTS / lights ignore the kw. Each builder
   no-ops on `snapshot_url=None`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import async_track_state_change_event, async_call_later
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
    CAMERA_PLATFORM_FRIGATE,
    NM_HAZARD_EXTERIOR_PERSON,
    NM_HAZARD_EXTERIOR_VEHICLE,
    EXTERIOR_CAMERA_KEY_ALIASES,
    NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE,
    NM_HAZARD_EXTERIOR_PERSON_DEFAULT_SEVERITY,
    NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP,
    CONF_EXTERIOR_SNAPSHOT_OFFSET_S,
    DEFAULT_EXTERIOR_SNAPSHOT_OFFSET_S,
    MIN_EXTERIOR_SNAPSHOT_OFFSET_S,
    MAX_EXTERIOR_SNAPSHOT_OFFSET_S,
    PERIMETER_BOOT_SETTLE_S,
    PERIMETER_PROTECT_PERSON_LEGS_ENABLED,
    CAMERA_RESOLUTION_CHANNEL_SUFFIXES,
    FRIGATE_SNAPSHOT_LABELS,
    TRACK_LINK_WINDOW_S,
    EXTERIOR_VEHICLE_NIGHT_START,
    EXTERIOR_VEHICLE_NIGHT_END,
    EXTERIOR_VEHICLE_ALERT_STATES,
    EXTERIOR_VEHICLE_ALERT_COOLDOWN_SECONDS,
    EXTERIOR_VEHICLE_SENSOR_SUFFIXES,
    EXTERIOR_ANIMAL_SENSOR_SUFFIXES,
)
from .domain_coordinators.base import Severity

_LOGGER = logging.getLogger(__name__)

# Window in seconds within which an egress crossing suppresses a perimeter alert
EGRESS_SUPPRESSION_WINDOW_SECONDS = 120  # 2 minutes

# Frigate HA-bus event name — community convention (published by an operator
# MQTT-to-event automation OR the mqtt-fires-event bridge). Not fired by the
# frigate custom component itself; degrades gracefully when absent.
FRIGATE_EVENTS_BUS_EVENT = "frigate_events"


class PerimeterAlertManager:
    """Monitor perimeter cameras and escalate person detections via NM."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the perimeter alert manager."""
        self.hass = hass
        self._unsub_perimeter: list[Any] = []
        self._unsub_egress: list[Any] = []
        self._unsub_vehicle: list[Any] = []
        self._unsub_animal: list[Any] = []
        self._unsub_frigate_events: Any = None
        # Timestamps of last alert per CAMERA KEY (cycle 2 fused-sourcing).
        # Was entity_id — changed so a physical event visible on both the
        # F1 base sensor AND the F2 `_2` sibling produces at most ONE alert.
        self._last_alert: dict[str, datetime] = {}
        # Independent cooldown namespace for the vehicle alert path so a
        # vehicle alert can never mute a person alert on the same camera.
        self._last_vehicle_alert: dict[str, datetime] = {}
        # Timestamp of most recent egress camera activation
        self._last_egress_time: datetime | None = None
        # person_binary_sensor entity_id -> resolved platform (frigate/unifiprotect/...)
        self._sensor_platforms: dict[str, str] = {}
        # person_binary_sensor entity_id -> configured camera.* entity_id
        self._sensor_to_camera: dict[str, str] = {}
        # Frigate camera name -> most recent event_id (updated via frigate_events bus)
        self._frigate_last_event_id: dict[str, str] = {}
        # One-shot log gates
        self._legacy_deprecation_warned = False
        self._legacy_fallback_logged = False
        self._absolutize_relative_logged = False
        self._active = False
        # A-M3: track pending async_call_later unsub handles for teardown
        self._pending_dispatches: list[Any] = []
        # A-M1 / C-mut-a: in-flight guard (per person-sensor entity_id)
        self._dispatch_in_flight: set[str] = set()
        # Fix-up (2026-08-06, A-H3/B-HIGH-1/D-M1): vehicle path mirror.
        # Add BEFORE any await/scheduling so 2 edges (base + `_2`) 5ms apart
        # produce exactly ONE emit even when snapshot resolution defers.
        self._vehicle_in_flight: set[str] = set()
        # Fix-up (2026-08-06, A-L5, C-L1): one-shot WARN gates.
        self._severity_map_miss_warned: set[tuple[str, str, str]] = set()
        self._feed_linker_warn_gates: set[str] = set()
        # Fix-up (2026-08-06, #12): late-registration re-scan (EVENT_
        # HOMEASSISTANT_STARTED) cleanup handle.
        self._unsub_started: Any = None
        # B-HIGH-2: perimeter-local settle timestamp
        self._setup_time: datetime | None = None

    async def async_setup(self) -> None:
        """Set up perimeter camera listeners.

        Resolves perimeter camera entities from the integration config entry
        via CameraIntegrationManager, then subscribes to state changes on the
        resolved person-detection binary_sensors. Returns immediately if no
        perimeter cameras are configured.
        """
        perimeter_infos = self._resolve_camera_infos(CONF_PERIMETER_CAMERAS)
        egress_infos = self._resolve_camera_infos(CONF_EGRESS_CAMERAS)

        # Flatten to sensor lists + cache platforms / camera-entity mapping.
        # Cycle 2 fused-sourcing (F1-retirement insurance): also accept the
        # rising edge from the `_2` sibling person sensor (F2 parallel host).
        # Per-camera cooldown + in-flight gates dedup so one physical event
        # visible on both hosts still yields ONE alert.
        # Dedup subscription set across configured/base/`_2`/Protect legs so
        # a camera whose configured `person_binary_sensor` IS ALREADY the
        # Protect leg (or the `_2` sibling) does not get double-subscribed.
        # 2026-08-06 protect-person-legs fix-up (A-M3 assumption):
        # Frigate's `<slug>_person_occupancy` slug and UniFi Protect's
        # `<slug>_person_detected` slug are assumed to reference the SAME
        # physical camera on THIS install (co-anchor via camera-key collapse).
        # If a future install has a Frigate slug that ALIASES a Protect slug
        # belonging to a DIFFERENT camera, camera-key collapse would silence
        # a legitimate second-camera alert. The cycle-3 resolver co-anchoring
        # is the structural fix for that case; today the assumption holds.
        perimeter_sensors: list[str] = []
        _perimeter_seen: set[str] = set()
        egress_sensors: list[str] = []
        _egress_seen: set[str] = set()

        def _append_sensor(
            target: list[str],
            seen: set[str],
            sensor: str,
            platform: str,
            cam: str,
        ) -> bool:
            if not sensor or sensor in seen:
                return False
            target.append(sensor)
            seen.add(sensor)
            self._sensor_platforms[sensor] = platform
            self._sensor_to_camera[sensor] = cam
            return True

        def _leg_tag(sensor: str, sibling: bool) -> str:
            protect = sensor.endswith("_person_detected_2") if sibling \
                else sensor.endswith("_person_detected")
            if sibling:
                return "protect2" if protect else "frigate2"
            return "protect" if protect else "frigate"

        def _wire_camera(
            cam_entity_id: str,
            info: Any,
            target: list[str],
            seen: set[str],
            role: str,  # "perimeter" | "egress"
        ) -> None:
            base_bs = info.person_binary_sensor
            if not base_bs:
                return
            legs_found: list[str] = []
            # A-L1: tag only on successful append (dedup can absorb the base).
            if _append_sensor(target, seen, base_bs, info.platform or "", cam_entity_id):
                legs_found.append(_leg_tag(base_bs, sibling=False))
            sibling = self._fused_sibling(base_bs)
            if sibling and _append_sensor(
                target, seen, sibling, info.platform or "", cam_entity_id,
            ):
                legs_found.append(_leg_tag(sibling, sibling=True))
                _LOGGER.info(
                    "PerimeterAlertManager: fused source for %s — also "
                    "watching %s (both hosts feed the same camera key)",
                    base_bs, sibling,
                )
            elif not sibling and role == "perimeter":
                _LOGGER.warning(
                    "PerimeterAlertManager: no `_2` sibling found for %s — "
                    "F2 host detections will not alert; F1 retirement will "
                    "silence this camera until sourcing is refit.", base_bs,
                )
            # 2026-08-06 protect-person-legs: add the Protect smart-detect
            # legs where present. Kill-switch gated inside _protect_person_legs.
            # Dedup absorbs the case where the configured base already IS
            # the Protect leg (or its `_2`).
            for protect_leg in self._protect_person_legs(
                base_bs, camera_entity_id=cam_entity_id,
            ):
                # Platform tag is intentionally NOT Frigate so
                # _resolve_snapshot_url_and_delay falls through to the
                # entity_picture fallback for Protect legs.
                if _append_sensor(
                    target, seen, protect_leg, "unifiprotect", cam_entity_id,
                ):
                    legs_found.append(
                        "protect2" if protect_leg.endswith("_2") else "protect"
                    )
            # A-L4 / B-LOW-B4: coverage inventory at setup only, INFO level,
            # gated on the kill switch (so a byte-identical reversion also
            # skips the new log surface).
            if PERIMETER_PROTECT_PERSON_LEGS_ENABLED:
                _LOGGER.info(
                    "PerimeterAlertManager: %s camera %s person-leg "
                    "coverage: %s (base=%s)",
                    role, cam_entity_id, legs_found, base_bs,
                )

        for cam_entity_id, info in perimeter_infos:
            _wire_camera(cam_entity_id, info, perimeter_sensors,
                         _perimeter_seen, "perimeter")

        for cam_entity_id, info in egress_infos:
            _wire_camera(cam_entity_id, info, egress_sensors,
                         _egress_seen, "egress")

        # Hotfix 2026-08-06 (operator-reported interior leak): install the
        # exterior camera allowlist on the linker so the frigate_events bus
        # cannot open tracks for interior cameras (playroom incident).
        # Keys derived the same way every consumer derives them.
        try:
            _linker = self.hass.data.get(DOMAIN, {}).get(
                "exterior_track_linker"
            )
            if _linker is not None:
                _allowed = set()
                for _sensor in perimeter_sensors + egress_sensors:
                    _k = self._camera_key_for_sensor(_sensor)
                    if _k:
                        _allowed.add(_k)
                if _allowed:
                    _linker.set_allowed_cameras(_allowed)
        except Exception:  # noqa: BLE001 — allowlist install must not break setup
            _LOGGER.warning(
                "PerimeterAlertManager: linker allowlist install failed",
                exc_info=True,
            )

        # Hotfix 2026-08-06 (operator-reported interior leak): install the
        # exterior camera allowlist on the linker so the frigate_events bus
        # cannot open tracks for interior cameras (playroom incident).
        # Keys derived the same way every consumer derives them.
        try:
            _linker = self.hass.data.get(DOMAIN, {}).get(
                "exterior_track_linker"
            )
            if _linker is not None:
                _allowed = set()
                for _sensor in perimeter_sensors + egress_sensors:
                    _k = self._camera_key_for_sensor(_sensor)
                    if _k:
                        _allowed.add(_k)
                if _allowed:
                    _linker.set_allowed_cameras(_allowed)
        except Exception:  # noqa: BLE001 — allowlist install must not break setup
            _LOGGER.warning(
                "PerimeterAlertManager: linker allowlist install failed",
                exc_info=True,
            )

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

        @callback
        def _on_perimeter_state_change(event: Event) -> None:
            """Handle perimeter camera person detection state change.

            Delegates to _on_perimeter_event so the boot-spurious gate
            (B-HIGH-2) is a REAL production method the test suite can
            drive directly — a test-file replica of this logic went
            green under production mutation (Bug Class #62, caught by
            orchestrator drill 2026-08-01).
            """
            self._on_perimeter_event(event)

        self._unsub_perimeter.append(
            async_track_state_change_event(
                self.hass,
                perimeter_sensors,
                _on_perimeter_state_change,
            )
        )

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

        # Subscribe to Frigate events bus — best-effort snapshot event_id capture.
        # If nothing ever publishes `frigate_events`, this listener is harmless.
        @callback
        def _on_frigate_event(event: Event) -> None:
            # A-M2: only cache event_id for label in FRIGATE_SNAPSHOT_LABELS
            # (currently {"person"}). Clear the cache on the event's `end`
            # message so a stale car/animal id never bleeds into a later
            # person alert.
            try:
                after = event.data.get("after") or {}
                label = str(after.get("label") or "").lower()
                camera = after.get("camera")
                event_id = after.get("id")
                msg_type = str(event.data.get("type") or "").lower()
                if not camera or label not in FRIGATE_SNAPSHOT_LABELS:
                    return
                cam_key = str(camera)
                if msg_type == "end":
                    self._frigate_last_event_id.pop(cam_key, None)
                    return
                if event_id:
                    self._frigate_last_event_id[cam_key] = str(event_id)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Frigate event parse failed", exc_info=True)

        self._unsub_frigate_events = self.hass.bus.async_listen(
            FRIGATE_EVENTS_BUS_EVENT, _on_frigate_event
        )

        # Cycle 2: vehicle + animal ingress paths. Vehicle rising edges may
        # dispatch a deep-night alert (_async_handle_vehicle_trigger); animal
        # rising edges only feed the linker for census/episode. Both use
        # binary sensors on the same perimeter cameras.
        vehicle_sensors: list[str] = []
        animal_sensors: list[str] = []
        for cam_entity_id, info in perimeter_infos:
            base_bs = info.person_binary_sensor or ""
            if not base_bs:
                continue
            v = self._derive_sibling_sensor(
                base_bs, EXTERIOR_VEHICLE_SENSOR_SUFFIXES,
            )
            if v:
                vehicle_sensors.append(v)
                self._sensor_to_camera[v] = cam_entity_id
                v2 = self._fused_sibling(v)
                if v2:
                    vehicle_sensors.append(v2)
                    self._sensor_to_camera[v2] = cam_entity_id
                else:
                    _LOGGER.warning(
                        "PerimeterAlertManager: no `_2` sibling found for "
                        "vehicle sensor %s — F2 host vehicle events will "
                        "not dispatch.", v,
                    )
            else:
                _LOGGER.warning(
                    "PerimeterAlertManager: no vehicle sibling sensor "
                    "found for %s (searched suffixes=%s)",
                    base_bs, EXTERIOR_VEHICLE_SENSOR_SUFFIXES,
                )
            a = self._derive_sibling_sensor(
                base_bs, EXTERIOR_ANIMAL_SENSOR_SUFFIXES,
            )
            if a:
                animal_sensors.append(a)
                self._sensor_to_camera[a] = cam_entity_id
                a2 = self._fused_sibling(a)
                if a2:
                    animal_sensors.append(a2)
                    self._sensor_to_camera[a2] = cam_entity_id
                else:
                    _LOGGER.warning(
                        "PerimeterAlertManager: no `_2` sibling found for "
                        "animal sensor %s — F2 host animal events will "
                        "not feed the linker.", a,
                    )
            else:
                _LOGGER.warning(
                    "PerimeterAlertManager: no animal sibling sensor "
                    "found for %s (searched suffixes=%s)",
                    base_bs, EXTERIOR_ANIMAL_SENSOR_SUFFIXES,
                )

        if vehicle_sensors:
            @callback
            def _on_vehicle_state_change(event: Event) -> None:
                try:
                    new_state = event.data.get("new_state")
                    old_state = event.data.get("old_state")
                    if not (new_state and new_state.state == "on"):
                        return
                    if old_state is None or old_state.state == "on":
                        return
                    ent = event.data.get("entity_id", "")
                    self.hass.async_create_task(
                        self._async_handle_vehicle_trigger(ent)
                    )
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "PerimeterAlertManager: vehicle state change raised",
                        exc_info=True,
                    )

            self._unsub_vehicle.append(
                async_track_state_change_event(
                    self.hass, vehicle_sensors, _on_vehicle_state_change,
                )
            )
            _LOGGER.info(
                "PerimeterAlertManager: monitoring %d vehicle sensor(s) "
                "(deep-night alert window %02d-%02d, states=%s)",
                len(vehicle_sensors),
                EXTERIOR_VEHICLE_NIGHT_START,
                EXTERIOR_VEHICLE_NIGHT_END,
                sorted(EXTERIOR_VEHICLE_ALERT_STATES),
            )

        if animal_sensors:
            @callback
            def _on_animal_state_change(event: Event) -> None:
                try:
                    new_state = event.data.get("new_state")
                    old_state = event.data.get("old_state")
                    if not (new_state and new_state.state == "on"):
                        return
                    if old_state is None or old_state.state == "on":
                        return
                    # Fix-up (2026-08-06, B-M2): boot-settle gate on the
                    # animal path — RestoreEntity replay must NOT synthesize
                    # phantom animal census bumps.
                    if self._setup_time is not None:
                        elapsed = (
                            dt_util.now() - self._setup_time
                        ).total_seconds()
                        if elapsed < PERIMETER_BOOT_SETTLE_S:
                            return
                    ent = event.data.get("entity_id", "")
                    self._feed_linker(ent, "animal")
                except Exception:  # noqa: BLE001
                    _LOGGER.debug(
                        "PerimeterAlertManager: animal state change raised",
                        exc_info=True,
                    )

            self._unsub_animal.append(
                async_track_state_change_event(
                    self.hass, animal_sensors, _on_animal_state_change,
                )
            )
            _LOGGER.info(
                "PerimeterAlertManager: monitoring %d animal sensor(s) "
                "(digest-only — feeds linker, no NM dispatch)",
                len(animal_sensors),
            )

        # Fix-up (2026-08-06, item 12): one-shot post-start re-scan so any
        # sensors that register their entity_registry entry AFTER our setup
        # (late MQTT discovery, integration reload) get picked up. The
        # `_fused_sibling` / `_derive_sibling_sensor` calls now consult the
        # entity registry directly (not just hass.states), so this listener
        # covers the residual "registered strictly after async_setup" case.
        try:
            try:
                from homeassistant.const import (  # noqa: PLC0415
                    EVENT_HOMEASSISTANT_STARTED,
                )
            except Exception:  # noqa: BLE001
                EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"

            @callback
            def _on_started(_event: Any) -> None:
                self._rescan_siblings(perimeter_infos)

            self._unsub_started = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _on_started
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PerimeterAlertManager: HA_STARTED re-scan listener "
                "registration failed", exc_info=True,
            )

        self._setup_time = dt_util.now()
        self._active = True

    async def async_teardown(self) -> None:
        """Remove all state listeners."""
        for unsub in self._unsub_perimeter:
            unsub()
        self._unsub_perimeter.clear()

        for unsub in self._unsub_egress:
            unsub()
        self._unsub_egress.clear()

        for unsub in self._unsub_vehicle:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._unsub_vehicle.clear()
        for unsub in self._unsub_animal:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._unsub_animal.clear()

        if self._unsub_started is not None:
            try:
                self._unsub_started()
            except Exception:  # noqa: BLE001
                pass
            self._unsub_started = None

        if self._unsub_frigate_events is not None:
            try:
                self._unsub_frigate_events()
            except Exception:  # noqa: BLE001
                pass
            self._unsub_frigate_events = None

        # A-M3: cancel any pending delayed dispatches
        for unsub in self._pending_dispatches:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._pending_dispatches.clear()
        self._dispatch_in_flight.clear()

        self._active = False
        _LOGGER.debug("PerimeterAlertManager: torn down")

    async def _async_handle_perimeter_trigger(self, entity_id: str) -> None:
        """Evaluate a perimeter person detection and escalate if warranted."""
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

        # --- 3. Check per-camera cooldown (outer, authoritative rate limit) ---
        # Cycle 2 (fused-sourcing dedup): key by camera, not sensor entity_id,
        # so an event visible on both the F1 base sensor and the F2 `_2`
        # sibling still consumes ONE cooldown slot -> ONE alert.
        cooldown_key = self._camera_key_for_sensor(entity_id) or entity_id
        last_alert = self._last_alert.get(cooldown_key)
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

        # A-M1 / C-mut-a: in-flight guard. Second trigger while a dispatch
        # is in flight (possibly awaiting delayed snapshot) is suppressed
        # without touching cooldown. Cooldown reservation is deferred to
        # AFTER successful dispatch so a failed notify does not mute the
        # camera for 5 minutes.
        # Cycle 2: key in-flight by camera (fused-sourcing).
        if cooldown_key in self._dispatch_in_flight:
            _LOGGER.debug(
                "PerimeterAlertManager: %s trigger suppressed — dispatch "
                "already in flight for camera %s",
                entity_id, cooldown_key,
            )
            return

        # --- 3b. Redesign (Tier 3 fix-up): NO same-track suppression path.
        # Every event that passes the per-camera cooldown gate DISPATCHES.
        # Same-track continuations may be severity-DEMOTED (only when
        # CONFIDENT) or ESCALATED (approach/circling); they are never
        # silenced. INV-XT reduces to "≤ 1 dispatch per camera per cooldown"
        # which is exactly INV-XP — no separate silencing gate.

        # --- 4. Resolve severity from house state (D2, fail-safe) ---
        # C-mut-d: if the resolver itself raises, fall back to CRITICAL so
        # the docstring guarantee ("any exception → CRITICAL") holds even
        # if a downstream helper is broken.
        try:
            severity = self._severity_for_current_house_state()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "PerimeterAlertManager: severity resolver raised (%s) — "
                "coercing to CRITICAL (fail-safe).", exc,
            )
            severity = Severity.CRITICAL

        # --- 4b. Severity-map coercion (Tier 3 fix-up: DEMOTE, NEVER SILENCE).
        # Rules (kill switch gates the whole block — TRACK_LINK_WINDOW_S == 0
        # means no coercion, byte-identical to no-linker baseline):
        #   * FIRST alert of any track (alert_count == 0)   → today's severity, no map lookup.
        #   * CONTINUATION with confident pass_by classification
        #     (camera_count >= 2 AND classification == "pass_by")
        #                                                    → map value may DEMOTE, floor = LOW.
        #   * CONTINUATION with approach/circling            → map value may only RAISE
        #                                                     (never below today's severity).
        #   * Any other continuation (unclassified / single-hop / unconfident)
        #                                                    → today's severity untouched.
        #   * Map miss / unknown severity name               → today's severity untouched.
        # The severity floor is Severity.LOW — the map may never produce
        # total silence (DIGEST → LOW). The path narrative + latest snapshot
        # ride every dispatch (see enrichment block below).
        linker = self.hass.data.get(DOMAIN, {}).get("exterior_track_linker")
        _linker_camera = self._camera_key_for_sensor(entity_id)
        if (
            linker is not None
            and _linker_camera
            and TRACK_LINK_WINDOW_S > 0  # kill-switch gate
            # "Path Aware Notifications" switch — judgment layer only.
            # OFF → classic per-camera severity (LOUDER, never silent);
            # tracking/census/narrative unaffected.
            and getattr(linker, "smart_alerts_enabled", True)
        ):
            try:
                track = linker.find_owning_track(
                    _linker_camera, "person", now
                )
                house_state = self._get_house_state()
                if track is not None and house_state:
                    is_first_alert = track.alert_count == 0
                    classification = linker.classify(track)
                    confident_passby = (
                        classification == "pass_by"
                        and track.camera_count >= 2
                    )
                    label_map = NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP.get(
                        track.label, {}
                    )
                    state_map = label_map.get(house_state, {})
                    sev_name = state_map.get(classification)
                    coerced = None
                    if sev_name:
                        if sev_name == "DIGEST":
                            coerced = Severity.LOW
                        else:
                            try:
                                coerced = Severity[sev_name]
                            except KeyError:
                                coerced = None
                    if coerced is None or is_first_alert:
                        # First alert OR map miss → keep today's severity.
                        pass
                    elif confident_passby:
                        # Continuation + confident pass_by → allow demotion.
                        new_sev = max(coerced, Severity.LOW)
                        if new_sev != severity:
                            _LOGGER.info(
                                "PerimeterAlertManager: severity DEMOTED "
                                "%s→%s (track %s, label=%s, state=%s, "
                                "class=%s, camera_count=%d, alerts=%d)",
                                severity.name, new_sev.name,
                                track.track_id, track.label, house_state,
                                classification, track.camera_count,
                                track.alert_count,
                            )
                            severity = new_sev
                    elif classification in ("approach", "circling"):
                        # Continuation + approach/circling → only RAISE.
                        if coerced > severity:
                            _LOGGER.info(
                                "PerimeterAlertManager: severity ESCALATED "
                                "%s→%s (track %s, label=%s, state=%s, "
                                "class=%s)",
                                severity.name, coerced.name,
                                track.track_id, track.label, house_state,
                                classification,
                            )
                            severity = coerced
                    # else: unconfident classification → today's severity.
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "PerimeterAlertManager: severity map coercion raised "
                    "— keeping today's severity (fail-open).",
                    exc_info=True,
                )

        # --- 5. Resolve snapshot URL (D4) ---
        snapshot_url, delay_s = self._resolve_snapshot_url_and_delay(entity_id)

        # --- 6. Dispatch (NM primary, legacy fallback) ---
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        legacy_service, legacy_target = self._get_notify_config()

        # Both set → NM wins, one-shot deprecation WARN.
        if nm is not None and getattr(nm, "enabled", False) and legacy_service:
            if not self._legacy_deprecation_warned:
                _LOGGER.warning(
                    "PerimeterAlertManager: CONF_PERIMETER_ALERT_NOTIFY_SERVICE "
                    "is deprecated when NotificationManager is enabled — routing "
                    "via NM. Clear the legacy field to silence this warning; "
                    "disable NM to force the legacy path."
                )
                self._legacy_deprecation_warned = True

        title = "Perimeter Alert — Person Detected"
        message = (
            f"Person detected on perimeter camera {entity_id} "
            f"at {now.strftime('%H:%M:%S')}."
        )

        # build/exterior-track: enrich the message with the linker's path
        # narrative when a track owns this camera hop. Best-effort only —
        # linker absent / no track / any exception falls through to the
        # per-camera message above. Kill-switch gated.
        #
        # Note (B-M2): fresh narrative rides EACH new camera's dispatch
        # under the redesign — every dispatch re-renders path_string against
        # the latest owning track, so repeats do NOT reuse a stale message.
        linker = self.hass.data.get(DOMAIN, {}).get("exterior_track_linker")
        _linker_camera = self._camera_key_for_sensor(entity_id)
        if (
            linker is not None
            and _linker_camera
            and TRACK_LINK_WINDOW_S > 0  # kill-switch gate
        ):
            try:
                track = linker.find_owning_track(
                    _linker_camera, "person", now
                )
                if track is not None and len(track.hops) > 1:
                    message = (
                        f"Person track — {linker.path_string(track)}. "
                        f"Latest camera: {entity_id} at {now.strftime('%H:%M:%S')}."
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "PerimeterAlertManager: linker path enrichment failed",
                    exc_info=True,
                )

        # A-M1 short-circuit: no channels at all → don't reserve, don't
        # add in-flight, WARN and return.
        if (nm is None or not getattr(nm, "enabled", False)) and not legacy_service:
            _LOGGER.warning(
                "PerimeterAlertManager: person detected on %s but neither "
                "NM nor legacy notify_service is configured — skipping.",
                entity_id,
            )
            return

        self._dispatch_in_flight.add(cooldown_key)

        async def _do_dispatch(_now: Any = None) -> None:
            # A-M3: don't run after teardown / during HA shutdown
            if not self._active or getattr(self.hass, "is_stopping", False):
                self._dispatch_in_flight.discard(cooldown_key)
                return
            dispatched_ok = False
            try:
                if nm is not None and getattr(nm, "enabled", False):
                    try:
                        await nm.async_notify(
                            coordinator_id="perimeter_alert",
                            severity=severity,
                            title=title,
                            message=message,
                            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
                            location=entity_id,
                            snapshot_url=snapshot_url,
                        )
                        dispatched_ok = True
                        _LOGGER.info(
                            "PerimeterAlertManager: NM notify dispatched for %s "
                            "(severity=%s, snapshot=%s)",
                            entity_id, severity.name, bool(snapshot_url),
                        )
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.error(
                            "PerimeterAlertManager: NM notify failed for %s: %s",
                            entity_id, exc,
                        )
                    # D6 hook placeholder: future security-auto-follow can
                    # subscribe to a SIGNAL_NM_EXTERIOR_PERSON dispatch emitted
                    # here to pre-alarm the security coordinator. Not built.
                elif legacy_service:
                    if not self._legacy_fallback_logged:
                        _LOGGER.info(
                            "PerimeterAlertManager: NM absent/disabled — using "
                            "legacy notify service '%s' (deprecated path).",
                            legacy_service,
                        )
                        self._legacy_fallback_logged = True
                    try:
                        await self._async_send_legacy_notification(
                            legacy_service, legacy_target, entity_id, now
                        )
                        dispatched_ok = True
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.error(
                            "PerimeterAlertManager: legacy dispatch raised "
                            "for %s: %s", entity_id, exc,
                        )
                # A-M1: reserve cooldown ONLY after a successful dispatch.
                # A failed notify leaves the camera unmuted so the next
                # trigger within 5min can still alert.
                if dispatched_ok:
                    # Cycle 2: reserve cooldown by camera_key (fused-sourcing).
                    self._last_alert[cooldown_key] = now
                    # build/exterior-track: attribute the alert to the
                    # owning open track so future events on the same track
                    # can refine cadence (approach/circling still alert;
                    # pass_by demotes). REFINEMENT ONLY — never bypasses
                    # the per-camera cooldown gate above (INV-XP).
                    _linker = self.hass.data.get(DOMAIN, {}).get(
                        "exterior_track_linker"
                    )
                    _cam_key = self._camera_key_for_sensor(entity_id)
                    if _linker is not None and _cam_key:
                        try:
                            _linker.note_alert_dispatched(_cam_key, "person", now)
                        except Exception:  # noqa: BLE001
                            _LOGGER.debug(
                                "PerimeterAlertManager: linker "
                                "note_alert_dispatched failed",
                                exc_info=True,
                            )
            finally:
                self._dispatch_in_flight.discard(cooldown_key)

        if delay_s > 0:
            @callback
            def _scheduled_dispatch(_now: Any) -> None:
                # Bug Class #42: named callback (never a lambda wrapping
                # async_create_task) so the anti-pattern grep stays clean.
                self.hass.async_create_task(_do_dispatch())

            # A-M3: track handle so teardown can cancel.
            unsub = async_call_later(self.hass, delay_s, _scheduled_dispatch)
            self._pending_dispatches.append(unsub)
        else:
            await _do_dispatch()

        _LOGGER.info(
            "PerimeterAlertManager: alert processed for %s at %s (severity=%s)",
            entity_id,
            now.isoformat(),
            severity.name,
        )

    # ------------------------------------------------------------------
    # D2: severity mapping
    # ------------------------------------------------------------------

    def _severity_for_current_house_state(self) -> Severity:
        """Return Severity for the current house_state (fail-safe → CRITICAL)."""
        state = self._get_house_state()
        name = NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE.get(
            state, NM_HAZARD_EXTERIOR_PERSON_DEFAULT_SEVERITY
        )
        try:
            return Severity[name]
        except KeyError:
            _LOGGER.warning(
                "PerimeterAlertManager: unknown severity name '%s' for state "
                "'%s' — coercing to CRITICAL (fail-safe).",
                name, state,
            )
            return Severity.CRITICAL

    def _get_house_state(self) -> str:
        """Return the current house_state string via the canonical accessor.

        Mirrors `domain_coordinators/energy.py:_get_house_state` (v5.37.0). Any
        absence / exception collapses to "" → fail-safe CRITICAL upstream.
        """
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is None:
                return ""
            return str(getattr(manager, "house_state", "") or "")
        except Exception:  # noqa: BLE001
            return ""

    # ------------------------------------------------------------------
    # D4: snapshot resolution
    # ------------------------------------------------------------------

    def _resolve_snapshot_url_and_delay(
        self, sensor_entity_id: str
    ) -> tuple[str | None, int]:
        """Return (snapshot_url, dispatch_delay_seconds) for the given sensor.

        - Frigate + cached event_id: URL is at-detection-time; delay = 0.
        - Fallback: entity_picture of the camera + configured offset delay.
        - No camera resolvable / no picture: (None, 0) — never blocks alert.
        """
        platform = self._sensor_platforms.get(sensor_entity_id, "")
        camera_entity_id = self._sensor_to_camera.get(sensor_entity_id, "")

        if platform == CAMERA_PLATFORM_FRIGATE:
            # Derive frigate camera name from the person binary_sensor id:
            #   binary_sensor.<camera_name>_person_occupancy
            cam_name = None
            if sensor_entity_id.startswith("binary_sensor."):
                base = sensor_entity_id[len("binary_sensor."):]
                # Fix-up (2026-08-06, B-LOW-B3): route through the shared
                # `_strip_person_family_suffixes` helper so this Frigate
                # cache-key derivation cannot drift from
                # `_camera_key_for_sensor`. Also strips trailing `_2`.
                # Protect legs never reach this branch (platform check
                # above short-circuits them), so behavior for Protect
                # legs is unchanged.
                stem, _matched = self._strip_person_family_suffixes(base)
                if stem is not None:
                    cam_name = stem
                else:
                    if base.endswith("_2"):
                        base = base[:-2]
                    cam_name = base
            event_id = self._frigate_last_event_id.get(cam_name or "")
            if event_id:
                # Verified URL shape — ~/ha-config/custom_components/frigate/
                # views.py:317 (`NotificationsProxyView`).
                return (
                    self._absolutize(
                        f"/api/frigate/notifications/{event_id}/snapshot.jpg"
                    ),
                    0,
                )

        # Live fallback: use entity_picture + configurable offset.
        offset_s = self._get_snapshot_offset()
        picture_url: str | None = None
        if camera_entity_id:
            try:
                cam_state = self.hass.states.get(camera_entity_id)
                if cam_state is not None:
                    picture_url = cam_state.attributes.get("entity_picture")
            except Exception:  # noqa: BLE001
                picture_url = None
        return self._absolutize(picture_url), offset_s

    _PERSON_FAMILY_SUFFIXES: tuple[str, ...] = (
        "_person_occupancy",
        "_person_detected",
        "_person",
    )

    @classmethod
    def _strip_person_family_suffixes(
        cls, base: str,
    ) -> tuple[str | None, str | None]:
        """Return (stem, matched_suffix) for a bare sensor slug.

        Fix-up (2026-08-06, B-LOW-B3): single source of truth for the
        person-family suffix set consumed by BOTH `_camera_key_for_sensor`
        and `_resolve_snapshot_url_and_delay`. `base` MUST NOT include the
        `binary_sensor.` prefix. Trailing `_2` (fused-sourcing) is stripped
        first. When no person-family suffix matches, returns (None, None) —
        the caller decides whether to fall through to another suffix family.
        """
        if not base:
            return (None, None)
        if base.endswith("_2"):
            base = base[:-2]
        for suf in cls._PERSON_FAMILY_SUFFIXES:
            if base.endswith(suf):
                return (base[: -len(suf)], suf)
        return (None, None)

    def _camera_key_for_sensor(self, sensor_entity_id: str) -> str | None:
        """Return the Frigate camera name (linker key) for a binary_sensor.

        Cycle 2: also strips vehicle/animal suffixes and the trailing `_2`
        HA disambiguation (fused-sourcing) so ALL sensor families collapse
        to a single camera key (`_last_alert` / `_dispatch_in_flight` /
        vehicle cooldown are all host-independent).
        """
        try:
            if not sensor_entity_id.startswith("binary_sensor."):
                return None
            base = sensor_entity_id[len("binary_sensor."):]
            slug, _matched = self._strip_person_family_suffixes(base)
            if slug is None:
                # Fall through for vehicle/animal families below.
                if base.endswith("_2"):
                    base = base[:-2]
                for suf in EXTERIOR_VEHICLE_SENSOR_SUFFIXES:
                    if base.endswith(suf):
                        slug = base[: -len(suf)]
                        break
            if slug is None:
                for suf in EXTERIOR_ANIMAL_SENSOR_SUFFIXES:
                    if base.endswith(suf):
                        slug = base[: -len(suf)]
                        break
            if slug is None:
                slug = base
            # Fix-up (2026-08-06, item 14): alias live sensor prefix onto
            # the adjacency-graph key (e.g. armcrestpooloverhead → armcrest).
            return EXTERIOR_CAMERA_KEY_ALIASES.get(slug, slug)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # Cycle 2 helpers: fused sourcing + vehicle/animal derivation
    # ------------------------------------------------------------------

    def _rescan_siblings(self, perimeter_infos: list) -> None:
        """Fix-up (2026-08-06, item 12): one-shot re-scan after HA_STARTED.

        Re-derives vehicle/animal siblings; if any are now discoverable via
        the entity registry that weren't at setup, subscribes to them and
        logs the recovery. Does NOT drop existing subscriptions.
        """
        try:
            existing = set(self._sensor_to_camera.keys())
            added_vehicle: list[str] = []
            added_animal: list[str] = []
            for cam_entity_id, info in perimeter_infos:
                base_bs = getattr(info, "person_binary_sensor", "") or ""
                if not base_bs:
                    continue
                # Late-registered `_2` person sibling.
                sib = self._fused_sibling(base_bs)
                if sib and sib not in existing:
                    self._sensor_to_camera[sib] = cam_entity_id
                    self._sensor_platforms[sib] = getattr(info, "platform", "") or ""
                    self._unsub_perimeter.append(
                        async_track_state_change_event(
                            self.hass, [sib],
                            lambda ev: self._on_perimeter_event(ev),
                        )
                    )
                    _LOGGER.info(
                        "PerimeterAlertManager: late-registered person "
                        "sibling %s subscribed post-HA_STARTED.", sib,
                    )
                # A-M2 fix-up: also re-probe Protect person legs so any
                # UniFi Protect entity whose registry entry appears AFTER
                # our async_setup (integration reload, late discovery) is
                # picked up. Dedup guard is the existing `existing` set —
                # same one used by the person `_2` sibling above — so a
                # leg already subscribed at setup is not re-subscribed.
                for protect_leg in self._protect_person_legs(
                    base_bs, camera_entity_id=cam_entity_id,
                ):
                    if protect_leg in existing:
                        continue
                    self._sensor_to_camera[protect_leg] = cam_entity_id
                    self._sensor_platforms[protect_leg] = "unifiprotect"
                    self._unsub_perimeter.append(
                        async_track_state_change_event(
                            self.hass, [protect_leg],
                            lambda ev: self._on_perimeter_event(ev),
                        )
                    )
                    existing.add(protect_leg)
                    _LOGGER.info(
                        "PerimeterAlertManager: late-registered Protect "
                        "person leg %s subscribed post-HA_STARTED.",
                        protect_leg,
                    )
                # Vehicle / animal are logged only — new subscriptions
                # need the callback closures set up at async_setup; we log
                # and let the operator reload if a late-registered
                # vehicle/animal sensor needs live wiring.
                v = self._derive_sibling_sensor(
                    base_bs, EXTERIOR_VEHICLE_SENSOR_SUFFIXES,
                )
                if v and v not in existing:
                    added_vehicle.append(v)
                a = self._derive_sibling_sensor(
                    base_bs, EXTERIOR_ANIMAL_SENSOR_SUFFIXES,
                )
                if a and a not in existing:
                    added_animal.append(a)
            if added_vehicle or added_animal:
                _LOGGER.warning(
                    "PerimeterAlertManager: late-registered vehicle/animal "
                    "sensors detected post-HA_STARTED (vehicle=%s, "
                    "animal=%s); reload perimeter alerting to subscribe.",
                    added_vehicle, added_animal,
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PerimeterAlertManager: _rescan_siblings raised",
                exc_info=True,
            )

    def _entity_exists(self, entity_id: str) -> bool:
        """True if entity is in the entity registry (and enabled) OR has a live state.

        Fix-up (2026-08-06, A-M2/B-LOW-1): the entity registry carries the
        entity even before its first state publication, so late-boot
        subscription no longer requires a live state snapshot. Falls back
        to hass.states so behavior degrades gracefully when the registry
        stub is unavailable (tests / early boot).

        Fix-up (2026-08-06, review-2 A-M1): a disabled registry entry is
        treated as ABSENT — HA does not publish state for disabled entities,
        so subscribing to one is a silent no-op. We fall through to the live
        states check so a stub / operator override that still publishes a
        state is honored. This same guard now covers `_fused_sibling` and
        `_protect_person_legs` (both call through here) — the sibling gap
        was pre-existing and is fixed in passing.
        """
        try:
            from homeassistant.helpers import (  # noqa: PLC0415
                entity_registry as er,
            )
            reg = er.async_get(self.hass)
            if reg is not None:
                entry = reg.async_get(entity_id)
                if entry is not None and getattr(entry, "disabled_by", None) is None:
                    return True
        except Exception:  # noqa: BLE001
            pass
        try:
            return self.hass.states.get(entity_id) is not None
        except Exception:  # noqa: BLE001
            return False

    def _fused_sibling(self, entity_id: str) -> str | None:
        """Return the `_2` sibling binary sensor if it exists.

        Cycle 2 fused-sourcing: F1/F2 are parallel MQTT devices since the
        2026-08-01 prefix split; F2 sensors are HA-disambiguated with `_2`.
        Uses the entity registry (durable across restart / pre-state
        publication) via _entity_exists.
        """
        if not entity_id or not entity_id.startswith("binary_sensor."):
            return None
        candidate = f"{entity_id}_2"
        return candidate if self._entity_exists(candidate) else None

    def _protect_person_legs(
        self,
        person_bs: str,
        camera_entity_id: str | None = None,
    ) -> list[str]:
        """Return the Protect person legs for a base person binary_sensor.

        2026-08-06 protect-person-legs cycle. UniFi Protect exposes an
        independent person smart-detect binary_sensor whose entity slug
        follows `<camera_slug>_person_detected` (+ `_2` when the camera has
        two sensor entities registered). We derive candidate stems from
        BOTH the base person sensor's slug AND (fix-up A-L2) the configured
        camera entity id — the latter with the resolution-channel suffix
        stripped so `camera.rear_ptz_high_resolution_channel` yields
        `rear_ptz` and recovers `binary_sensor.rear_ptz_person_detected`.
        `EXTERIOR_CAMERA_KEY_ALIASES` is applied on each stem so an alias
        registered for the linker key (armcrestpooloverhead → armcrest)
        also aliases the Protect-leg probe. Registry-based via
        `_entity_exists`, matching the cycle-2 fused-sourcing durability
        rule (survives pre-state-publication and filters disabled entries).

        Returns [] when the kill switch is off, when no stem can be
        derived, or when neither the base nor `_2` Protect leg exists in
        the registry for any candidate stem. Never re-returns the base
        sensor itself — the caller dedups against the already-subscribed
        set.
        """
        if not PERIMETER_PROTECT_PERSON_LEGS_ENABLED:
            return []
        stems: list[str] = []

        def _add_stem(raw: str | None) -> None:
            if not raw:
                return
            aliased = EXTERIOR_CAMERA_KEY_ALIASES.get(raw, raw)
            for candidate in (raw, aliased):
                if candidate and candidate not in stems:
                    stems.append(candidate)

        # Stem 1: from the person binary_sensor slug (as before).
        if person_bs and person_bs.startswith("binary_sensor."):
            base = person_bs[len("binary_sensor."):]
            stem_bs, _matched = self._strip_person_family_suffixes(base)
            _add_stem(stem_bs)

        # Stem 2 (A-L2 fix-up): from the configured camera entity id, with
        # resolution-channel suffixes stripped. Recovers rear_ptz /
        # utilities_ptz whose Frigate person_bs slug diverges from the
        # camera slug.
        if camera_entity_id and camera_entity_id.startswith("camera."):
            cam_slug = camera_entity_id[len("camera."):]
            for suf in CAMERA_RESOLUTION_CHANNEL_SUFFIXES:
                if cam_slug.endswith(suf):
                    cam_slug = cam_slug[: -len(suf)]
                    break
            _add_stem(cam_slug)

        if not stems:
            return []
        legs: list[str] = []
        seen: set[str] = set()
        for stem in stems:
            primary = f"binary_sensor.{stem}_person_detected"
            if primary not in seen and self._entity_exists(primary):
                legs.append(primary)
                seen.add(primary)
            secondary = f"{primary}_2"
            if secondary not in seen and self._entity_exists(secondary):
                legs.append(secondary)
                seen.add(secondary)
        return legs

    def _derive_sibling_sensor(
        self, person_bs: str, suffixes: tuple[str, ...]
    ) -> str | None:
        """Derive a vehicle/animal binary sensor id from a person sensor id."""
        if not person_bs or not person_bs.startswith("binary_sensor."):
            return None
        base = person_bs[len("binary_sensor."):]
        stem = None
        for p in ("_person_occupancy", "_person_detected", "_person"):
            if base.endswith(p):
                stem = base[: -len(p)]
                break
        if stem is None:
            stem = base
        for suf in suffixes:
            cand = f"binary_sensor.{stem}{suf}"
            if self._entity_exists(cand):
                return cand
        return None

    def _feed_linker(self, sensor_entity_id: str, label: str) -> None:
        """Feed ExteriorTrackLinker.observe() from a rising-edge binary sensor.

        Kill-switch gated (TRACK_LINK_WINDOW_S <= 0 → no-op, mirrors
        linker's own gate). Used for animal (digest-only, no NM) and
        vehicle (deep-night NM gate lives in _async_handle_vehicle_trigger,
        called BEFORE this feed for vehicles). Best-effort — failures are
        WARN-once per sensor (C-L1) then debug.
        """
        if TRACK_LINK_WINDOW_S <= 0:
            return
        try:
            linker = self.hass.data.get(DOMAIN, {}).get(
                "exterior_track_linker"
            )
            if linker is None:
                return
            cam_key = self._camera_key_for_sensor(sensor_entity_id)
            if not cam_key:
                return
            linker.observe(
                camera=cam_key,
                label=label,
                event_id=None,
                score=0.0,
                sub_label=None,
                now=dt_util.now(),
            )
        except Exception:  # noqa: BLE001
            # Fix-up (2026-08-06, C-L1): WARN-once per sensor, then debug.
            gate_key = f"{label}:{sensor_entity_id}"
            if gate_key not in self._feed_linker_warn_gates:
                self._feed_linker_warn_gates.add(gate_key)
                _LOGGER.warning(
                    "PerimeterAlertManager: first linker feed (%s) failed "
                    "for %s — subsequent failures at debug.",
                    label, sensor_entity_id, exc_info=True,
                )
            else:
                _LOGGER.debug(
                    "PerimeterAlertManager: linker feed (%s) failed for %s",
                    label, sensor_entity_id, exc_info=True,
                )

    def _in_vehicle_night_window(self, now: datetime) -> bool:
        """True when `now` is inside the deep-night vehicle-alert window.

        Window semantics match _is_in_alert_hours: start < end is same-day,
        start >= end wraps at midnight. Rung-1 module constants.
        """
        start = EXTERIOR_VEHICLE_NIGHT_START
        end = EXTERIOR_VEHICLE_NIGHT_END
        h = now.hour
        if start == end:
            return True
        if start < end:
            return start <= h < end
        return h >= start or h < end

    async def _async_handle_vehicle_trigger(
        self, sensor_entity_id: str
    ) -> None:
        """Deep-night vehicle alert path (cycle 2).

        Always feeds the linker (census + episode) — subject to the kill
        switch. Dispatches an NM alert ONLY when (a) inside the deep-night
        window AND (b) house_state ∈ EXTERIOR_VEHICLE_ALERT_STATES AND
        (c) linker.tracking_enabled AND TRACK_LINK_WINDOW_S > 0 (fix-up
        item 8: kill-switch mutes the vehicle emitter — byte-identical
        backout to no-linker baseline) AND (d) the OWNING track has not
        yet dispatched a vehicle alert (item 7 first-alert-per-track:
        bounds parked-car storm to one page per track).

        Per-camera cooldown uses its own namespace so it can never mute
        the person alert. In-flight guard mirrors the person path (item 2).
        """
        now = dt_util.now()
        # Fix-up (2026-08-06, item 9): snapshot house_state ONCE at handler
        # entry so gate + severity see identical values (no split-brain).
        # Transient "" / unknown fails CLOSED for vehicles (bias: silence a
        # potentially-legit alert during boot rather than emit a mis-scoped
        # HIGH).
        house_state = self._get_house_state()
        if self._setup_time is not None:
            elapsed = (now - self._setup_time).total_seconds()
            if elapsed < PERIMETER_BOOT_SETTLE_S:
                _LOGGER.debug(
                    "PerimeterAlertManager: ignoring vehicle trigger for %s "
                    "within boot settle (%.1fs of %ds)",
                    sensor_entity_id, elapsed, PERIMETER_BOOT_SETTLE_S,
                )
                return
        # Always feed the linker (census / episode / narrative).
        self._feed_linker(sensor_entity_id, "car")

        # Fix-up (2026-08-06, item 8): kill-switch gates the ENTIRE vehicle
        # emitter — TRACK_LINK_WINDOW_S<=0 OR linker.tracking_enabled=False
        # mutes NM dispatch (linker feed already gated above; symmetrical).
        linker_kill = self.hass.data.get(DOMAIN, {}).get(
            "exterior_track_linker"
        )
        if TRACK_LINK_WINDOW_S <= 0 or (
            linker_kill is not None
            and not getattr(linker_kill, "tracking_enabled", True)
        ):
            _LOGGER.debug(
                "PerimeterAlertManager: vehicle emitter muted by "
                "kill-switch (window=%d, tracking_enabled=%s) — %s",
                TRACK_LINK_WINDOW_S,
                getattr(linker_kill, "tracking_enabled", None),
                sensor_entity_id,
            )
            return

        if not self._in_vehicle_night_window(now):
            _LOGGER.debug(
                "PerimeterAlertManager: vehicle on %s outside deep-night "
                "window (%02d-%02d) — digest-only, no NM dispatch.",
                sensor_entity_id,
                EXTERIOR_VEHICLE_NIGHT_START,
                EXTERIOR_VEHICLE_NIGHT_END,
            )
            return
        # Fix-up item 9: use the SNAPSHOT taken at handler entry; transient
        # "" / unknown does not satisfy the state set → fails CLOSED.
        if house_state not in EXTERIOR_VEHICLE_ALERT_STATES:
            _LOGGER.debug(
                "PerimeterAlertManager: vehicle on %s deep-night but "
                "house_state=%s (need %s) — no NM dispatch.",
                sensor_entity_id, house_state,
                sorted(EXTERIOR_VEHICLE_ALERT_STATES),
            )
            return
        cooldown_key = (
            self._camera_key_for_sensor(sensor_entity_id) or sensor_entity_id
        )
        last = self._last_vehicle_alert.get(cooldown_key)
        if last is not None:
            seconds_since = (now - last).total_seconds()
            if seconds_since < EXTERIOR_VEHICLE_ALERT_COOLDOWN_SECONDS:
                _LOGGER.debug(
                    "PerimeterAlertManager: vehicle alert suppressed for %s "
                    "— cooldown (%.0fs of %ds)",
                    cooldown_key, seconds_since,
                    EXTERIOR_VEHICLE_ALERT_COOLDOWN_SECONDS,
                )
                return

        # Fix-up (2026-08-06, item 2): in-flight guard SYNCHRONOUS BEFORE
        # any await/scheduling, mirroring the person path. Two edges 5ms
        # apart (base + `_2`) with a delayed snapshot must yield exactly
        # ONE NM emit. Discarded in _do_vehicle_dispatch's finally.
        if cooldown_key in self._vehicle_in_flight:
            _LOGGER.debug(
                "PerimeterAlertManager: vehicle trigger for %s suppressed "
                "— dispatch already in flight for camera %s",
                sensor_entity_id, cooldown_key,
            )
            return

        # Fix-up (2026-08-06, item 7): FIRST alert per track. Once the
        # owning open track has any alert_count, subsequent vehicle events
        # on the same track are digest-only (linker feed already ran).
        # Bounds parked-car storm (worst case ~96 pages/night observed) and
        # a returning-family arriving at 23:30 to ONE page (treated as
        # confirmation). The RESIDUAL is a family arrival during 'away' at
        # 23:30 — accepted as legitimate first-alert confirmation.
        linker_gate = self.hass.data.get(DOMAIN, {}).get(
            "exterior_track_linker"
        )
        if linker_gate is not None:
            try:
                owning = linker_gate.find_owning_track(
                    cooldown_key, "car", now,
                )
                if owning is not None and owning.alert_count > 0:
                    _LOGGER.debug(
                        "PerimeterAlertManager: vehicle first-alert-per-"
                        "track gate — track %s already alerted (count=%d), "
                        "digest-only.",
                        owning.track_id, owning.alert_count,
                    )
                    return
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "PerimeterAlertManager: vehicle first-alert-per-track "
                    "check raised — proceeding (fail-open).",
                    exc_info=True,
                )

        # Resolve severity + path narrative.
        severity = Severity.HIGH
        classification = "pass_by"
        path_narrative: str | None = None
        try:
            linker = self.hass.data.get(DOMAIN, {}).get(
                "exterior_track_linker"
            )
            if linker is not None and cooldown_key:
                track = linker.find_owning_track(cooldown_key, "car", now)
                if track is not None:
                    classification = linker.classify(track)
                    if len(track.hops) > 1:
                        path_narrative = linker.path_string(track)
            label_map = NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP.get("car", {})
            state_map = label_map.get(house_state, {})
            sev_name = state_map.get(classification)
            if sev_name and sev_name != "DIGEST":
                try:
                    severity = Severity[sev_name]
                except KeyError:
                    pass
            elif not sev_name:
                # Fix-up (2026-08-06, A-L5): WARN-once per (label, state,
                # classification) so unmapped combinations surface without
                # log-flooding. Falls through to the default HIGH severity.
                miss_key = ("car", house_state or "", classification)
                if miss_key not in self._severity_map_miss_warned:
                    self._severity_map_miss_warned.add(miss_key)
                    _LOGGER.warning(
                        "PerimeterAlertManager: severity map miss for "
                        "car/%s/%s — defaulting to %s.",
                        house_state, classification, severity.name,
                    )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PerimeterAlertManager: vehicle severity resolve raised",
                exc_info=True,
            )

        snapshot_url, delay_s = self._resolve_snapshot_url_and_delay(
            sensor_entity_id
        )

        title = "Perimeter Alert — Vehicle (deep-night)"
        if path_narrative:
            message = (
                f"Vehicle: {path_narrative}. Latest camera: {cooldown_key} "
                f"at {now.strftime('%H:%M:%S')} (house_state={house_state})."
            )
        else:
            message = (
                f"Vehicle detected on {cooldown_key} at "
                f"{now.strftime('%H:%M:%S')} (deep-night, "
                f"house_state={house_state})."
            )

        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        legacy_service, legacy_target = self._get_notify_config()
        if (nm is None or not getattr(nm, "enabled", False)) and not legacy_service:
            _LOGGER.warning(
                "PerimeterAlertManager: vehicle on %s but no NM/legacy "
                "notify configured — skipping.", sensor_entity_id,
            )
            return

        # Fix-up (2026-08-06, item 2): reserve BEFORE any await/scheduling.
        self._vehicle_in_flight.add(cooldown_key)

        async def _do_vehicle_dispatch(_now: Any = None) -> None:
            # Track handle for pruning (item D-L2).
            _handle_ref = getattr(_do_vehicle_dispatch, "_handle", None)
            if not self._active or getattr(self.hass, "is_stopping", False):
                self._vehicle_in_flight.discard(cooldown_key)
                if _handle_ref is not None:
                    try:
                        self._pending_dispatches.remove(_handle_ref)
                    except ValueError:
                        pass
                return
            dispatched_ok = False
            try:
                if nm is not None and getattr(nm, "enabled", False):
                    try:
                        await nm.async_notify(
                            coordinator_id="perimeter_alert",
                            severity=severity,
                            title=title,
                            message=message,
                            # Fix-up (2026-08-06, A-H1/D-H1): distinct
                            # hazard_type so vehicle never collapses a
                            # subsequent person emission via NM boot-settle
                            # partitioning (keyed on (coord, hazard)).
                            hazard_type=NM_HAZARD_EXTERIOR_VEHICLE,
                            location=cooldown_key,
                            snapshot_url=snapshot_url,
                        )
                        dispatched_ok = True
                        _LOGGER.info(
                            "PerimeterAlertManager: vehicle NM dispatched "
                            "for %s (severity=%s, class=%s, state=%s)",
                            cooldown_key, severity.name, classification,
                            house_state,
                        )
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.error(
                            "PerimeterAlertManager: vehicle NM failed for "
                            "%s: %s", cooldown_key, exc,
                        )
                elif legacy_service:
                    try:
                        # Fix-up (2026-08-06, A-H2): legacy fallback must
                        # be labeled Vehicle, not Person.
                        await self._async_send_legacy_notification(
                            legacy_service, legacy_target,
                            cooldown_key, now,
                            label_family="vehicle",
                        )
                        dispatched_ok = True
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.error(
                            "PerimeterAlertManager: vehicle legacy dispatch "
                            "raised for %s: %s", cooldown_key, exc,
                        )
                if dispatched_ok:
                    # Fix-up (2026-08-06, A-M3): stamp with dispatch-time
                    # `now` (not the earlier handler-entry `now`) so a
                    # long snapshot delay does not undercount cooldown.
                    self._last_vehicle_alert[cooldown_key] = dt_util.now()
                    try:
                        _lk = self.hass.data.get(DOMAIN, {}).get(
                            "exterior_track_linker"
                        )
                        if _lk is not None:
                            _lk.note_alert_dispatched(
                                cooldown_key, "car", dt_util.now(),
                            )
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "PerimeterAlertManager: vehicle dispatch loop raised",
                    exc_info=True,
                )
            finally:
                self._vehicle_in_flight.discard(cooldown_key)
                # Fix-up (2026-08-06, D-L2): prune the pending-dispatch
                # handle on successful fire so the list does not grow.
                if _handle_ref is not None:
                    try:
                        self._pending_dispatches.remove(_handle_ref)
                    except ValueError:
                        pass

        if delay_s > 0:
            @callback
            def _scheduled_vehicle_dispatch(_now: Any) -> None:
                self.hass.async_create_task(_do_vehicle_dispatch())

            unsub = async_call_later(
                self.hass, delay_s, _scheduled_vehicle_dispatch
            )
            _do_vehicle_dispatch._handle = unsub  # type: ignore[attr-defined]
            self._pending_dispatches.append(unsub)
        else:
            await _do_vehicle_dispatch()

    def _absolutize(self, url: str | None) -> str | None:
        """A-H1: normalize a relative HA URL to absolute for external channels.

        Pushover / WhatsApp media fetchers cannot resolve `/api/...` — they
        need `https://host/api/...`. Prefer `hass.config.external_url`,
        fall back to `internal_url`. If neither is set, leave the URL
        relative (Companion-app-only degradation) and DEBUG-log ONCE.
        """
        if not url or "://" in url:
            return url
        base = None
        try:
            cfg = getattr(self.hass, "config", None)
            base = getattr(cfg, "external_url", None) or getattr(
                cfg, "internal_url", None
            )
        except Exception:  # noqa: BLE001
            base = None
        if not base:
            if not self._absolutize_relative_logged:
                _LOGGER.debug(
                    "PerimeterAlertManager: neither external_url nor "
                    "internal_url set — leaving snapshot URL relative "
                    "(Companion-only, Pushover/WhatsApp will drop image)."
                )
                self._absolutize_relative_logged = True
            return url
        return str(base).rstrip("/") + url

    def _get_snapshot_offset(self) -> int:
        """Read and clamp CONF_EXTERIOR_SNAPSHOT_OFFSET_S from config."""
        config = self._get_integration_config()
        try:
            raw = int(config.get(
                CONF_EXTERIOR_SNAPSHOT_OFFSET_S,
                DEFAULT_EXTERIOR_SNAPSHOT_OFFSET_S,
            ))
        except (TypeError, ValueError):
            raw = DEFAULT_EXTERIOR_SNAPSHOT_OFFSET_S
        if raw < MIN_EXTERIOR_SNAPSHOT_OFFSET_S:
            return MIN_EXTERIOR_SNAPSHOT_OFFSET_S
        if raw > MAX_EXTERIOR_SNAPSHOT_OFFSET_S:
            return MAX_EXTERIOR_SNAPSHOT_OFFSET_S
        return raw

    # ------------------------------------------------------------------
    # Legacy fallback path (NM disabled)
    # ------------------------------------------------------------------

    async def _async_send_legacy_notification(
        self,
        service: str,
        target: str | None,
        camera_entity_id: str,
        timestamp: datetime,
        label_family: str = "person",
    ) -> None:
        """Call the legacy notify service.

        Fix-up (2026-08-06, A-H2): parameterized by label family so the
        vehicle path fallback no longer mislabels the alert as Person.
        `camera_entity_id` is expected to be a camera key or display slug
        — displayed as-is (the caller passes cooldown_key for the vehicle
        path, which is the linker/graph key, not the raw sensor slug).
        """
        parts = service.split(".", 1)
        if len(parts) != 2:
            _LOGGER.error(
                "PerimeterAlertManager: invalid notify service format '%s' "
                "(expected 'domain.service')",
                service,
            )
            return

        service_domain, service_name = parts
        if label_family == "vehicle":
            title = "Perimeter Alert — Vehicle (deep-night)"
            noun = "Vehicle"
        else:
            title = "Perimeter Alert — Person Detected"
            noun = "Person"
        message = (
            f"{noun} detected on perimeter camera {camera_entity_id} "
            f"at {timestamp.strftime('%H:%M:%S')}."
        )

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
                "PerimeterAlertManager: legacy notification sent via %s for camera %s",
                service,
                camera_entity_id,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error(
                "PerimeterAlertManager: failed to send legacy notification via %s: %s",
                service,
                exc,
            )

    @callback
    def _on_perimeter_event(self, event: Event) -> None:
        """B-HIGH-2 boot-spurious gate + dispatch (production, test-driven).

        Ignore when old_state is None (initial publication) OR when the
        transition is on->on (attribute-only change, not a rising edge).
        Additionally, ignore any event within PERIMETER_BOOT_SETTLE_S of
        setup so RestoreEntity replay cannot fire spurious CRITICAL alerts.
        """
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not (new_state and new_state.state == "on"):
            return
        if old_state is None or old_state.state == "on":
            _LOGGER.debug(
                "PerimeterAlertManager: ignoring non-rising-edge event "
                "for %s (old=%s)", entity_id,
                None if old_state is None else old_state.state,
            )
            return
        if self._setup_time is not None:
            elapsed = (dt_util.now() - self._setup_time).total_seconds()
            if elapsed < PERIMETER_BOOT_SETTLE_S:
                _LOGGER.debug(
                    "PerimeterAlertManager: ignoring %s trigger within "
                    "boot settle window (%.1fs of %ds)",
                    entity_id, elapsed, PERIMETER_BOOT_SETTLE_S,
                )
                return
        # A-HIGH-3 (liveness fix): feed the linker off the rising edge as a
        # fallback for installs where `frigate_events` is not wired. The
        # linker's own observe() dedups per (camera,label) within a few
        # seconds so this is a no-op when the frigate_events subscriber
        # already fired.
        try:
            linker = self.hass.data.get(DOMAIN, {}).get(
                "exterior_track_linker"
            )
            cam_key = self._camera_key_for_sensor(entity_id)
            if linker is not None and cam_key:
                linker.observe(
                    camera=cam_key,
                    label="person",
                    event_id=None,
                    score=0.0,
                    sub_label=None,
                    now=dt_util.now(),
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PerimeterAlertManager: linker fallback observe failed",
                exc_info=True,
            )
        self.hass.async_create_task(
            self._async_handle_perimeter_trigger(entity_id)
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
        """Return True if current hour falls within the configured alert window."""
        config = self._get_integration_config()
        start = config.get(CONF_PERIMETER_ALERT_HOURS_START, DEFAULT_PERIMETER_ALERT_START)
        end = config.get(CONF_PERIMETER_ALERT_HOURS_END, DEFAULT_PERIMETER_ALERT_END)

        hour = now.hour
        if start == end:
            return True
        if start < end:
            return start <= hour < end
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

    def _resolve_camera_infos(self, conf_key: str) -> list[tuple[str, Any]]:
        """Return [(camera_entity_id, CameraInfo)] via CameraIntegrationManager.

        CameraInfo carries the person_binary_sensor + platform we need for
        snapshot routing (D4). Empty list when no manager / no cameras.
        """
        camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")
        if not camera_manager:
            return []

        config = self._get_integration_config()
        camera_entity_ids: list[str] = config.get(conf_key, [])
        if not camera_entity_ids:
            return []

        # Iterate configured cameras individually so we retain the
        # camera.* → CameraInfo back-pointer (resolve_configured_cameras
        # flattens the list and loses it). Only used for D4 live-fallback
        # snapshot (entity_picture lookup).
        pairs: list[tuple[str, Any]] = []
        for cam_id in camera_entity_ids:
            try:
                infos = camera_manager.resolve_camera_entity(cam_id)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "resolve_camera_entity failed for %s", cam_id, exc_info=True,
                )
                continue
            for info in infos:
                pairs.append((cam_id, info))
        return pairs

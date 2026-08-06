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
    NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE,
    NM_HAZARD_EXTERIOR_PERSON_DEFAULT_SEVERITY,
    NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP,
    CONF_EXTERIOR_SNAPSHOT_OFFSET_S,
    DEFAULT_EXTERIOR_SNAPSHOT_OFFSET_S,
    MIN_EXTERIOR_SNAPSHOT_OFFSET_S,
    MAX_EXTERIOR_SNAPSHOT_OFFSET_S,
    PERIMETER_BOOT_SETTLE_S,
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
        perimeter_sensors: list[str] = []
        for cam_entity_id, info in perimeter_infos:
            base_bs = info.person_binary_sensor
            if not base_bs:
                continue
            perimeter_sensors.append(base_bs)
            self._sensor_platforms[base_bs] = info.platform or ""
            self._sensor_to_camera[base_bs] = cam_entity_id
            sibling = self._fused_sibling(base_bs)
            if sibling:
                perimeter_sensors.append(sibling)
                self._sensor_platforms[sibling] = info.platform or ""
                self._sensor_to_camera[sibling] = cam_entity_id
                _LOGGER.info(
                    "PerimeterAlertManager: fused source for %s — also "
                    "watching %s (both hosts feed the same camera key)",
                    base_bs, sibling,
                )
            else:
                _LOGGER.warning(
                    "PerimeterAlertManager: no `_2` sibling found for %s — "
                    "F2 host detections will not alert; F1 retirement will "
                    "silence this camera until sourcing is refit.", base_bs,
                )

        egress_sensors = [
            info.person_binary_sensor
            for _, info in egress_infos
            if info.person_binary_sensor
        ]

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
                if base.endswith("_person_occupancy"):
                    cam_name = base[: -len("_person_occupancy")]
                else:
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
            if base.endswith("_2"):
                base = base[:-2]
            for suf in ("_person_occupancy", "_person_detected", "_person"):
                if base.endswith(suf):
                    return base[: -len(suf)]
            for suf in EXTERIOR_VEHICLE_SENSOR_SUFFIXES:
                if base.endswith(suf):
                    return base[: -len(suf)]
            for suf in EXTERIOR_ANIMAL_SENSOR_SUFFIXES:
                if base.endswith(suf):
                    return base[: -len(suf)]
            return base
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # Cycle 2 helpers: fused sourcing + vehicle/animal derivation
    # ------------------------------------------------------------------

    def _fused_sibling(self, entity_id: str) -> str | None:
        """Return the `_2` sibling binary sensor if it exists in HA.

        Cycle 2 fused-sourcing: F1/F2 are parallel MQTT devices since the
        2026-08-01 prefix split; F2 sensors are HA-disambiguated with `_2`.
        Returns None when the sibling does not exist so a WARN can surface.
        """
        if not entity_id or not entity_id.startswith("binary_sensor."):
            return None
        candidate = f"{entity_id}_2"
        try:
            if self.hass.states.get(candidate) is not None:
                return candidate
        except Exception:  # noqa: BLE001
            return None
        return None

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
            try:
                if self.hass.states.get(cand) is not None:
                    return cand
            except Exception:  # noqa: BLE001
                continue
        return None

    def _feed_linker(self, sensor_entity_id: str, label: str) -> None:
        """Feed ExteriorTrackLinker.observe() from a rising-edge binary sensor.

        Kill-switch gated; best-effort. Used for both animal (digest-only)
        and vehicle (deep-night gate lives in _async_handle_vehicle_trigger).
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

        Always feeds the linker (census + episode). Dispatches an NM alert
        ONLY when (a) inside the deep-night window AND (b) house_state ∈
        EXTERIOR_VEHICLE_ALERT_STATES. Per-camera cooldown uses its own
        namespace so it can never mute the person alert.
        """
        now = dt_util.now()
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

        if not self._in_vehicle_night_window(now):
            _LOGGER.debug(
                "PerimeterAlertManager: vehicle on %s outside deep-night "
                "window (%02d-%02d) — digest-only, no NM dispatch.",
                sensor_entity_id,
                EXTERIOR_VEHICLE_NIGHT_START,
                EXTERIOR_VEHICLE_NIGHT_END,
            )
            return
        house_state = self._get_house_state()
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

        async def _do_vehicle_dispatch(_now: Any = None) -> None:
            if not self._active or getattr(self.hass, "is_stopping", False):
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
                        await self._async_send_legacy_notification(
                            legacy_service, legacy_target,
                            cooldown_key, now,
                        )
                        dispatched_ok = True
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.error(
                            "PerimeterAlertManager: vehicle legacy dispatch "
                            "raised for %s: %s", cooldown_key, exc,
                        )
                if dispatched_ok:
                    self._last_vehicle_alert[cooldown_key] = now
                    try:
                        _lk = self.hass.data.get(DOMAIN, {}).get(
                            "exterior_track_linker"
                        )
                        if _lk is not None:
                            _lk.note_alert_dispatched(
                                cooldown_key, "car", now,
                            )
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "PerimeterAlertManager: vehicle dispatch loop raised",
                    exc_info=True,
                )

        if delay_s > 0:
            @callback
            def _scheduled_vehicle_dispatch(_now: Any) -> None:
                self.hass.async_create_task(_do_vehicle_dispatch())

            unsub = async_call_later(
                self.hass, delay_s, _scheduled_vehicle_dispatch
            )
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
    ) -> None:
        """Call the legacy notify service."""
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

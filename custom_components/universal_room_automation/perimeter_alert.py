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
        self._unsub_frigate_events: Any = None
        # Timestamps of last alert per camera person-binary-sensor entity_id
        self._last_alert: dict[str, datetime] = {}
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

        # Flatten to sensor lists + cache platforms / camera-entity mapping
        perimeter_sensors: list[str] = []
        for cam_entity_id, info in perimeter_infos:
            if info.person_binary_sensor:
                perimeter_sensors.append(info.person_binary_sensor)
                self._sensor_platforms[info.person_binary_sensor] = info.platform or ""
                self._sensor_to_camera[info.person_binary_sensor] = cam_entity_id

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

        # A-M1 / C-mut-a: in-flight guard. Second trigger while a dispatch
        # is in flight (possibly awaiting delayed snapshot) is suppressed
        # without touching cooldown. Cooldown reservation is deferred to
        # AFTER successful dispatch so a failed notify does not mute the
        # camera for 5 minutes.
        if entity_id in self._dispatch_in_flight:
            _LOGGER.debug(
                "PerimeterAlertManager: %s trigger suppressed — dispatch "
                "already in flight",
                entity_id,
            )
            return

        # --- 3b. Same-track suppression (build/exterior-track REFINEMENT
        # under INV-XP). Runs AFTER the per-camera cooldown gate so it can
        # only REDUCE the alert stream — a suppressed thread is one the
        # cooldown gate would have let through. Fail-open: linker
        # missing/absent/exception → NEVER suppress.
        # INV-XP invariant preserved: nothing in this block enables an
        # alert the cooldown gate would have blocked.
        linker = self.hass.data.get(DOMAIN, {}).get("exterior_track_linker")
        _linker_camera = self._camera_key_for_sensor(entity_id)
        if linker is not None and _linker_camera:
            try:
                if linker.same_track_should_suppress(
                    _linker_camera, "person", now
                ):
                    _LOGGER.info(
                        "PerimeterAlertManager: %s alert suppressed — "
                        "same-track (pass_by) refinement (INV-XT).",
                        entity_id,
                    )
                    # Still record the hop on the ORIGINAL thread's track so
                    # its path narrative + repeat machinery stay current.
                    try:
                        linker.note_alert_dispatched(
                            _linker_camera, "person", now
                        )
                    except Exception:  # noqa: BLE001
                        _LOGGER.debug(
                            "linker note_alert_dispatched (suppressed path) "
                            "failed", exc_info=True,
                        )
                    return
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "PerimeterAlertManager: same_track_should_suppress "
                    "raised — falling through (fail-open, no suppression).",
                    exc_info=True,
                )

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

        # --- 4b. Severity-map coercion (build/exterior-track).
        # When a linker track exists AND we have a house_state AND the
        # (label × state × classification) tuple resolves to a known
        # Severity name, coerce. Any miss → keep today's severity
        # (fail-open: person/unclassified defaults preserve today's
        # behavior exactly, per plan).
        #
        # Rationale for the map defaults (const.py NM_HAZARD_EXTERIOR_
        # TRACK_SEVERITY_MAP):
        #  - person/away/circling = CRITICAL (matches today; escalation
        #    room via repeat machinery + path narrative).
        #  - person/away/approach = HIGH (still alarming but headed toward
        #    an egress-adjacent camera vs a plain perimeter drift).
        #  - person/away/pass_by = MEDIUM (a single boundary hop while
        #    away is noisier than useful at CRITICAL — the last-night
        #    walker case the operator flagged).
        #  - car/away/circling = HIGH (deep-night vehicle circling while
        #    away is the operator's negative signal).
        #  - animal/* = DIGEST across the board (no CRITICAL urgency).
        # DIGEST has no Severity enum member; treated as Severity.LOW
        # (our lowest tier) so the map's demotion intent still applies.
        if linker is not None and _linker_camera:
            try:
                track = linker.latest_track_for_camera(
                    _linker_camera, "person"
                )
                house_state = self._get_house_state()
                if track is not None and house_state:
                    classification = linker.classify(track)
                    label_map = NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP.get(
                        track.label, {}
                    )
                    state_map = label_map.get(house_state, {})
                    sev_name = state_map.get(classification)
                    if sev_name:
                        if sev_name == "DIGEST":
                            coerced = Severity.LOW
                        else:
                            try:
                                coerced = Severity[sev_name]
                            except KeyError:
                                coerced = None
                        if coerced is not None and coerced != severity:
                            _LOGGER.info(
                                "PerimeterAlertManager: severity coerced "
                                "%s→%s via track map (label=%s, "
                                "state=%s, class=%s)",
                                severity.name, coerced.name, track.label,
                                house_state, classification,
                            )
                            severity = coerced
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
        # per-camera message above. INV-XP unweakened: this is message
        # enrichment, not a suppression/dispatch change.
        linker = self.hass.data.get(DOMAIN, {}).get("exterior_track_linker")
        _linker_camera = self._camera_key_for_sensor(entity_id)
        if linker is not None and _linker_camera:
            try:
                track = linker.latest_track_for_camera(_linker_camera, "person")
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

        self._dispatch_in_flight.add(entity_id)

        async def _do_dispatch(_now: Any = None) -> None:
            # A-M3: don't run after teardown / during HA shutdown
            if not self._active or getattr(self.hass, "is_stopping", False):
                self._dispatch_in_flight.discard(entity_id)
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
                    self._last_alert[entity_id] = now
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
                self._dispatch_in_flight.discard(entity_id)

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
        """Return the Frigate camera name (linker key) for a person binary_sensor.

        Matches _resolve_snapshot_url_and_delay's derivation so linker keys
        line up with the Frigate event bus's `after.camera` field.
        """
        try:
            if not sensor_entity_id.startswith("binary_sensor."):
                return None
            base = sensor_entity_id[len("binary_sensor."):]
            if base.endswith("_person_occupancy"):
                return base[: -len("_person_occupancy")]
            return base
        except Exception:  # noqa: BLE001
            return None

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

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
import os
import time as _time
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.event import (
    async_track_state_change_event, async_call_later,
    async_track_time_interval,
)
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
    PERIMETER_MULTI_ENGINE_LEGS_ENABLED,
    PERIMETER_PROTECT_PERSON_LEGS_ENABLED,  # DEPRECATED alias — retained one release
    CAMERA_RESOLUTION_CHANNEL_SUFFIXES,
    FRIGATE_SNAPSHOT_LABELS,
    FRIGATE_SNAPSHOT_ID_TTL_S,
    PERIMETER_SNAPSHOT_DIR,
    PERIMETER_SNAPSHOT_RETENTION_AGE_H,
    PERIMETER_SNAPSHOT_RETENTION_COUNT,
    PERIMETER_SNAPSHOT_ENGINE_PRECEDENCE,
    PERIMETER_SNAPSHOT_KILL_LEGACY_URL,
    PERIMETER_SNAPSHOT_SWEEP_INTERVAL_S,
    TRACK_LINK_WINDOW_S,
    EXTERIOR_VEHICLE_NIGHT_START,
    EXTERIOR_VEHICLE_NIGHT_END,
    EXTERIOR_VEHICLE_ALERT_STATES,
    EXTERIOR_VEHICLE_ALERT_COOLDOWN_SECONDS,
    EXTERIOR_VEHICLE_SENSOR_SUFFIXES,
    EXTERIOR_ANIMAL_SENSOR_SUFFIXES,
)
from .domain_coordinators.base import Severity
# F1 (cycle-3 fix-up): single source of truth for person-family suffix
# vocabulary — perimeter dedup MUST NOT drift from resolver discovery.
from .camera_resolver import _PERSON_SUFFIXES as _RESOLVER_PERSON_SUFFIXES

_LOGGER = logging.getLogger(__name__)

# Window in seconds within which an egress crossing suppresses a perimeter alert
EGRESS_SUPPRESSION_WINDOW_SECONDS = 120  # 2 minutes

# Frigate HA-bus event name — community convention (published by an operator
# MQTT-to-event automation OR the mqtt-fires-event bridge). Not fired by the
# frigate custom component itself; degrades gracefully when absent.
FRIGATE_EVENTS_BUS_EVENT = "frigate_events"

# F15 (cycle-3 fix-up 2026-08-07): pre-lowered alias table so lookups are
# case-insensitive on both sides at O(1) build cost.
_EXTERIOR_CAMERA_KEY_ALIASES_LC: dict[str, str] = {
    (k.lower() if isinstance(k, str) else k):
        (v.lower() if isinstance(v, str) else v)
    for k, v in EXTERIOR_CAMERA_KEY_ALIASES.items()
}


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
        # (event_id, cached_at) per canonical camera key; TTL-gated at
        # read (hotfix 2026-08-07 — see _on_frigate_event).
        self._frigate_last_event_id: dict[str, tuple[str, datetime]] = {}
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
        # Cycle-3 resolver-legs (2026-08-07): per-sensor engine tag from
        # CameraResolver.resolve_detection_legs(); consumed by the
        # disagreement telemetry. entity_id -> engine label
        # (frigate/frigate2/protect/protect2/reolink/amcrest/dahua).
        self._sensor_engine: dict[str, str] = {}
        # Disagreement telemetry: per-(camera_key, engine) cumulative
        # rising-edge counter + per-camera event counter for sole-firing
        # ratio. Observability only — never gates dispatch.
        self._leg_fire_counts: dict[tuple[str, str], int] = {}
        self._leg_sole_fire_counts: dict[tuple[str, str], int] = {}
        # Recent-fires log for sole-firing detection: per camera, a
        # bounded deque of (engine, ts) pairs within the last window.
        # Kept small — 32 entries per camera; sole-firing determined by
        # scan of the last WINDOW_S seconds. Reset lazily at fire time.
        self._recent_fires: dict[str, list[tuple[str, datetime]]] = {}
        # F1 (2026-08-07 fix-up cycle-4): remember the derived allowlist
        # so the SIGNAL_EXTERIOR_LINKER_READY handler can (re)install it
        # when the linker registers AFTER perimeter_alert.async_setup().
        # This is the true root cause of SECC-1 — the inline install at
        # setup time was DEAD CODE (linker not yet in hass.data).
        self._perimeter_allowlist: set[str] = set()
        # unsub for the linker-ready signal subscription.
        self._unsub_linker_ready: Any = None
        # SNAP-1 (2026-08-08): at-detection snapshot state.
        # Setup-time assertion result. When True, delivery falls back
        # to the legacy `media_url`/`attachment=<url>` shape byte-for-
        # byte (kill-switch semantics, auto-engaged on allowed-path or
        # www-privacy assertion failure).
        self._snapshot_kill_legacy_url: bool = bool(
            PERIMETER_SNAPSHOT_KILL_LEGACY_URL
        )
        # Frigate instance ids discovered from loaded config entries
        # (list of MQTT client_ids). Cached at setup; refreshed lazily.
        self._frigate_instance_ids: list[str] = []
        # camera_key -> chosen instance_id (learned on first success).
        self._camera_frigate_instance: dict[str, str] = {}
        # Structured last-capture ledger — observability signal exposed
        # to future dashboard/sensor without requiring a new entity now.
        # camera_key -> {"path", "engine", "wrote_at", "bytes"}.
        self._last_snapshot_capture: dict[str, dict[str, Any]] = {}
        # Periodic prune sweep unsub.
        self._unsub_snapshot_sweep: Any = None
        # One-shot log gates.
        self._snapshot_setup_error_logged: bool = False

    async def async_setup(self) -> None:
        """Set up perimeter camera listeners.

        Resolves perimeter camera entities from the integration config entry
        via CameraIntegrationManager, then subscribes to state changes on the
        resolved person-detection binary_sensors. Returns immediately if no
        perimeter cameras are configured.
        """
        # SNAP-1: prepare on-disk snapshot dir + assert invariants BEFORE
        # any capture is possible. On any failure, engage the kill switch
        # so delivery reverts to legacy URL form (never crashes setup).
        await self._async_setup_snapshot_dir()

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
            engine_by_leg: dict[str, str] = {}
            # Cycle-3 resolver-legs (2026-08-07): multi-integration leg
            # discovery via CameraResolver. Falls back to legacy base+`_2`
            # only when the kill switch is OFF or the resolver is
            # unavailable (early boot / test fixture without camera_manager).
            resolver_legs = self._resolve_legs(cam_entity_id, "person")
            if resolver_legs:
                # Union the resolver legs with the configured base so a
                # configured entity the resolver did not surface is still
                # subscribed (defensive dedup — cooldown/in-flight collapse
                # yields ONE alert regardless).
                base_engine = "frigate" if base_bs.endswith("_person_occupancy") else (
                    "protect" if base_bs.endswith("_person_detected") else "legacy"
                )
                if _append_sensor(target, seen, base_bs, info.platform or "", cam_entity_id):
                    legs_found.append(base_engine)
                    engine_by_leg[base_bs] = base_engine
                for leg in resolver_legs:
                    plat = leg.integration or ""
                    if _append_sensor(target, seen, leg.entity_id, plat, cam_entity_id):
                        legs_found.append(leg.engine)
                        engine_by_leg[leg.entity_id] = leg.engine
                # Safety net for entities that exist in hass.states but not
                # the entity_registry (test fixtures + some late-boot
                # scenarios): probe the direct `_2` sibling of the
                # configured base sensor and add it if `_entity_exists`
                # confirms it. Preserves the "no `_2` sibling found" WARN
                # semantic for the legacy fused-sourcing observability.
                sibling = f"{base_bs}_2"
                try:
                    if self._entity_exists(sibling) and sibling not in seen:
                        _e2 = "frigate2" if base_bs.endswith("_person_occupancy") else (
                            "protect2" if base_bs.endswith("_person_detected") else "legacy2"
                        )
                        if _append_sensor(target, seen, sibling, info.platform or "", cam_entity_id):
                            legs_found.append(_e2)
                            engine_by_leg[sibling] = _e2
                    elif (
                        not self._entity_exists(sibling)
                        and role == "perimeter"
                        # F8 (cycle-3 fix-up 2026-08-07): only Frigate has
                        # `_N` sibling semantics; native-AI bases have none,
                        # so WARN-ing on them was a boot-storm.
                        and base_bs.endswith("_person_occupancy")
                    ):
                        _LOGGER.warning(
                            "PerimeterAlertManager: no `_2` sibling found "
                            "for %s — F2 host detections will not alert.",
                            base_bs,
                        )
                except Exception:  # noqa: BLE001
                    pass
            else:
                # Legacy fallback path (kill switch OFF / no manager).
                for eid, engine in self._legacy_leg_fallback(base_bs, cam_entity_id, "person"):
                    if _append_sensor(target, seen, eid, info.platform or "", cam_entity_id):
                        legs_found.append(engine)
                        engine_by_leg[eid] = engine
                if (
                    role == "perimeter"
                    and len(legs_found) < 2
                    # F8 (cycle-3 fix-up 2026-08-07): only warn when the
                    # configured base is a Frigate `_person_occupancy`
                    # entity; native-AI bases have no `_N` sibling shape.
                    and base_bs.endswith("_person_occupancy")
                ):
                    _LOGGER.warning(
                        "PerimeterAlertManager: no `_2` sibling found for "
                        "%s — F2 host detections will not alert.", base_bs,
                    )
            # Record engine tags for the disagreement telemetry.
            self._sensor_engine.update(engine_by_leg)
            # A-L4 / B-LOW-B4: coverage inventory — grouped BY ENGINE per
            # the cycle-3 headline scope.
            if PERIMETER_MULTI_ENGINE_LEGS_ENABLED:
                _LOGGER.info(
                    "PerimeterAlertManager: %s camera %s person-leg "
                    "coverage by engine: %s (base=%s)",
                    role, cam_entity_id, sorted(set(legs_found)), base_bs,
                )
            # F7 (cycle-3 fix-up 2026-08-07): missing-alias tripwire — if
            # two subscribed legs produce DIFFERENT camera keys, the
            # cooldown/in-flight collapse breaks and both fire. WARN so
            # the operator sees the alias gap immediately.
            _distinct_keys: set[str] = set()
            for _eid in engine_by_leg.keys():
                _k = self._camera_key_for_sensor(_eid)
                if _k:
                    _distinct_keys.add(_k)
            if len(_distinct_keys) > 1:
                _LOGGER.warning(
                    "PerimeterAlertManager: %s camera %s legs resolve to "
                    ">1 camera key %s — cooldown/dedup will not collapse. "
                    "Add an EXTERIOR_CAMERA_KEY_ALIASES entry.",
                    role, cam_entity_id, sorted(_distinct_keys),
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
        # F9 (cycle-3 fix-up 2026-08-07): duplicated block below removed —
        # kept exactly one install site.
        # F1 (2026-08-07 fix-up cycle-4): derive the allowlist and REMEMBER
        # it. Then attempt inline install (covers the case where the linker
        # already exists — e.g. a re-setup after a reload). If the linker
        # is not yet registered (the ORIGINAL setup ordering — linker is
        # registered AFTER perimeter_alert.async_setup() in __init__.py),
        # subscribe to SIGNAL_EXTERIOR_LINKER_READY to install when it
        # fires. This closes the SECC-1 dead-code gap.
        _allowed = set()
        for _sensor in perimeter_sensors + egress_sensors:
            _k = self._camera_key_for_sensor(_sensor)
            if _k:
                _allowed.add(_k)
        self._perimeter_allowlist = _allowed
        try:
            _linker = self.hass.data.get(DOMAIN, {}).get(
                "exterior_track_linker"
            )
            if _linker is not None:
                if _allowed:
                    _linker.set_allowed_cameras(_allowed)
            else:
                _LOGGER.warning(
                    "PerimeterAlertManager: exterior_track_linker not yet "
                    "registered — deferring allowlist install to "
                    "SIGNAL_EXTERIOR_LINKER_READY (%d cameras staged)",
                    len(_allowed),
                )
        except Exception:  # noqa: BLE001 — allowlist install must not break setup
            _LOGGER.warning(
                "PerimeterAlertManager: linker allowlist install failed",
                exc_info=True,
            )

        # Wire the deferred install path unconditionally — the linker's
        # __init__ dispatches READY after registering, and if the signal
        # already fired before we got here, a subsequent linker re-setup
        # (e.g. reload) will re-fire it. Idempotent.
        try:
            from homeassistant.helpers.dispatcher import async_dispatcher_connect
            from .domain_coordinators.signals import (
                SIGNAL_EXTERIOR_LINKER_READY,
            )

            @callback
            def _install_on_ready() -> None:
                try:
                    _lk = self.hass.data.get(DOMAIN, {}).get(
                        "exterior_track_linker"
                    )
                    if _lk is None or not self._perimeter_allowlist:
                        return
                    _lk.set_allowed_cameras(self._perimeter_allowlist)
                    _LOGGER.info(
                        "PerimeterAlertManager: allowlist installed on "
                        "linker via READY signal (%d cameras)",
                        len(self._perimeter_allowlist),
                    )
                    # BOOTSANITY-1 (2026-08-08): sanity check the install
                    # actually took. On COLD BOOT the end-of-setup guard
                    # cannot fire (linker registers AFTER async_setup
                    # returns) — this READY-path check is the ONLY guard
                    # that runs on the normal boot ordering. If
                    # set_allowed_cameras returned but the linker's
                    # allowlist is still empty, it's a SECC-1 class
                    # regression (silent no-op install).
                    if not getattr(_lk, "_allowed_cameras", None):
                        _LOGGER.warning(
                            "PerimeterAlertManager: linker allowlist STILL "
                            "EMPTY after set_allowed_cameras() (%d cameras "
                            "staged) — SECC-1 class regression suspected",
                            len(self._perimeter_allowlist),
                        )
                except Exception:  # noqa: BLE001
                    _LOGGER.warning(
                        "PerimeterAlertManager: deferred allowlist install "
                        "failed",
                        exc_info=True,
                    )

            self._unsub_linker_ready = async_dispatcher_connect(
                self.hass, SIGNAL_EXTERIOR_LINKER_READY, _install_on_ready,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PerimeterAlertManager: could not subscribe to "
                "SIGNAL_EXTERIOR_LINKER_READY",
                exc_info=True,
            )

        # F1(e) (2026-08-07 fix-up cycle-4): boot-sanity WARNING. If
        # perimeter cameras are configured but the linker (once present)
        # has NO cameras in its allowlist, log at WARNING so this class
        # of bug (silent no-op install) surfaces to the operator.
        try:
            _linker_now = self.hass.data.get(DOMAIN, {}).get(
                "exterior_track_linker"
            )
            if (
                _allowed
                and _linker_now is not None
                and not getattr(_linker_now, "_allowed_cameras", None)
            ):
                _LOGGER.warning(
                    "PerimeterAlertManager: linker present but allowlist "
                    "empty after setup (%d cameras staged) — SECC-1 class "
                    "regression suspected",
                    len(_allowed),
                )
        except Exception:  # noqa: BLE001
            pass

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
                # Hotfix 2026-08-07 (operator: alerts with no picture):
                # (a) canonical lowercase key — CamelCase Frigate names
                #     (ReolinkStudyBPorchPTZ) could never match the
                #     lowercase stem lookup (same case-split family as
                #     the linker hotfix);
                # (b) do NOT clear on 'end' — Frigate snapshots remain
                #     fetchable after the event ends, and a brief
                #     walk-past ends before dispatch resolves, which
                #     erased the id exactly when it was needed. The id
                #     now persists with FRIGATE_SNAPSHOT_ID_TTL_S.
                cam_key = str(camera).strip().lower()
                if msg_type == "end":
                    return
                if event_id:
                    self._frigate_last_event_id[cam_key] = (
                        str(event_id), dt_util.utcnow(),
                    )
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
        # Cycle-3 resolver-legs (2026-08-07): vehicle+animal legs sourced
        # per-integration via CameraResolver instead of the retired
        # _derive_sibling_sensor + _fused_sibling pair.
        _v_seen: set[str] = set()
        _a_seen: set[str] = set()
        for cam_entity_id, info in perimeter_infos:
            base_bs = info.person_binary_sensor or ""
            v_legs = self._resolve_legs(cam_entity_id, "vehicle")
            a_legs = self._resolve_legs(cam_entity_id, "animal")
            if not v_legs and base_bs:
                v_legs = [type("L", (), {"entity_id": eid, "engine": eng,
                                          "integration": "", "device_id": ""})()
                          for (eid, eng) in self._legacy_leg_fallback(
                              base_bs, cam_entity_id, "vehicle")
                          if eid != base_bs]
            if not a_legs and base_bs:
                a_legs = [type("L", (), {"entity_id": eid, "engine": eng,
                                          "integration": "", "device_id": ""})()
                          for (eid, eng) in self._legacy_leg_fallback(
                              base_bs, cam_entity_id, "animal")
                          if eid != base_bs]
            v_engines: list[str] = []
            for leg in v_legs:
                if leg.entity_id in _v_seen:
                    continue
                _v_seen.add(leg.entity_id)
                vehicle_sensors.append(leg.entity_id)
                self._sensor_to_camera[leg.entity_id] = cam_entity_id
                self._sensor_engine[leg.entity_id] = leg.engine
                v_engines.append(leg.engine)
            a_engines: list[str] = []
            for leg in a_legs:
                if leg.entity_id in _a_seen:
                    continue
                _a_seen.add(leg.entity_id)
                animal_sensors.append(leg.entity_id)
                self._sensor_to_camera[leg.entity_id] = cam_entity_id
                self._sensor_engine[leg.entity_id] = leg.engine
                a_engines.append(leg.engine)
            if PERIMETER_MULTI_ENGINE_LEGS_ENABLED and (v_engines or a_engines):
                _LOGGER.info(
                    "PerimeterAlertManager: perimeter camera %s "
                    "vehicle-leg engines=%s animal-leg engines=%s",
                    cam_entity_id, sorted(set(v_engines)),
                    sorted(set(a_engines)),
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

        # SNAP-1: periodic prune sweep (safety net for low-traffic days
        # where no capture-write triggers the on-write prune).
        try:
            from datetime import timedelta as _td
            self._unsub_snapshot_sweep = async_track_time_interval(
                self.hass,
                self._on_snapshot_sweep_tick,
                _td(seconds=PERIMETER_SNAPSHOT_SWEEP_INTERVAL_S),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PerimeterAlertManager: snapshot sweep listener registration"
                " failed",
                exc_info=True,
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

        if self._unsub_snapshot_sweep is not None:
            try:
                self._unsub_snapshot_sweep()
            except Exception:  # noqa: BLE001
                pass
            self._unsub_snapshot_sweep = None

        if self._unsub_linker_ready is not None:
            try:
                self._unsub_linker_ready()
            except Exception:  # noqa: BLE001
                pass
            self._unsub_linker_ready = None

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
        # SNAP-1: capture an at-detection snapshot to a LOCAL FILE (best
        # effort). When kill switch is engaged (const, or setup-time
        # assertion failure) this returns None and delivery keeps the
        # legacy URL shape byte-for-byte. Capture time is decoupled
        # from cooldown/dispatch/llmvision-delay because it runs BEFORE
        # the scheduler delay below — the operator's core requirement.
        # A capture failure NEVER blocks the alert.
        snapshot_path: str | None = None
        if not self._snapshot_kill_legacy_url:
            try:
                snapshot_path = await self._capture_at_detection_snapshot(
                    entity_id,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "PerimeterAlertManager: snapshot capture raised for %s "
                    "— degrading to no-image", entity_id, exc_info=True,
                )
                snapshot_path = None
            # SNAP-1: when we successfully captured a local file, delay is 0
            # (the file is already at-detection; no reason to defer for a
            # subsequent live-fallback grab). Preserve delay for the URL
            # fallback path — that keeps CONF_EXTERIOR_SNAPSHOT_OFFSET_S
            # semantics unchanged.
            if snapshot_path:
                delay_s = 0

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
                            snapshot_path=snapshot_path,
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
            cached = self._frigate_last_event_id.get(
                (cam_name or "").strip().lower()
            )
            event_id = None
            if cached:
                _eid, _ts = cached
                _age = (dt_util.utcnow() - _ts).total_seconds()
                if 0 <= _age < FRIGATE_SNAPSHOT_ID_TTL_S:
                    event_id = _eid
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

    # F1 (cycle-3 fix-up 2026-08-07): derive the person-family suffix set
    # FROM the resolver's vocabulary (imported at module load) so this
    # class cannot drift again. Sort LONGEST-FIRST so `_smart_motion_human`
    # strips before shorter matches would incorrectly claim the suffix.
    _PERSON_FAMILY_SUFFIXES: tuple[str, ...] = tuple(
        sorted(_RESOLVER_PERSON_SUFFIXES, key=len, reverse=True)
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
            # F15 (cycle-3 fix-up 2026-08-07): case-insensitive both sides.
            slug_lc = slug.lower() if isinstance(slug, str) else slug
            return _EXTERIOR_CAMERA_KEY_ALIASES_LC.get(slug_lc, slug)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # Cycle 2 helpers: fused sourcing + vehicle/animal derivation
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Cycle-3 resolver-legs (2026-08-07): retired _fused_sibling +
    # _protect_person_legs + _derive_sibling_sensor. All multi-engine
    # discovery now flows through CameraResolver.resolve_detection_legs.
    # Sensor-side dedup + cooldown/in-flight camera-key collapse stays.
    # ------------------------------------------------------------------

    # Sole-firing observation window (seconds). Two engines' rising
    # edges on the same camera within this window are considered the
    # SAME physical event; if only one engine fires in the window, it
    # counts as sole. Rung-1 module-scoped: only observability semantics.
    _SOLE_FIRE_WINDOW_S = 60

    def _resolve_legs(
        self, camera_entity_id: str, family: str,
    ) -> list[Any]:
        """Return DetectionLegs for a configured camera + family.

        Kill-switch semantics (PERIMETER_MULTI_ENGINE_LEGS_ENABLED=False):
        return []; caller falls back to legacy base-only + `_2` sibling
        discovery (byte-identical pre-cycle behavior for the person path).
        """
        if not PERIMETER_MULTI_ENGINE_LEGS_ENABLED:
            return []
        try:
            camera_manager = self.hass.data.get(DOMAIN, {}).get("camera_manager")
            if camera_manager is None:
                return []
            resolver = camera_manager._get_resolver()
            if resolver is None:
                return []
            return resolver.resolve_detection_legs(
                camera_entity_id, family,
                stem_aliases=EXTERIOR_CAMERA_KEY_ALIASES,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PerimeterAlertManager._resolve_legs failed for %s (%s)",
                camera_entity_id, family, exc_info=True,
            )
            return []

    def _legacy_leg_fallback(
        self, base_bs: str, camera_entity_id: str, family: str,
    ) -> list[tuple[str, str]]:
        """Byte-identical pre-cycle-3 fallback: base + `_2` sibling only.

        Returns [(entity_id, engine_tag)]. Used ONLY when the kill
        switch is OFF or the resolver returns [] (no camera_manager /
        early boot). Engine tag is best-effort ("legacy") — sufficient
        for coverage log; disagreement telemetry gets a coarser view
        but the kill switch is expected to be exceptional.
        """
        out: list[tuple[str, str]] = []
        if not base_bs:
            return out
        out.append((base_bs, "legacy"))
        candidate = f"{base_bs}_2"
        try:
            if self._entity_exists(candidate):
                out.append((candidate, "legacy2"))
        except Exception:  # noqa: BLE001
            pass
        # F3 (cycle-3 fix-up 2026-08-07): OFF path must preserve v5.58.0
        # Protect stem-probed leg so kill-switch pull does NOT silently
        # drop Protect coverage. Recovers the retired _protect_person_legs
        # shape (Frigate base -> Protect `_person_detected` sibling, plus
        # `_2`). Also recognizes a Dahua `_smart_motion_human` base so an
        # operator whose configured base is native-AI keeps person
        # detection under the OFF/fallback path.
        if family == "person" and base_bs.startswith("binary_sensor."):
            base_slug = base_bs[len("binary_sensor."):]
            stem, _matched = self._strip_person_family_suffixes(base_slug)
            if stem is None:
                stem = base_slug
            # Camera-side stem recovery (channel-suffix strip + alias) so
            # rear_ptz_high_resolution_channel yields rear_ptz.
            cam_stem = None
            if camera_entity_id and camera_entity_id.startswith("camera."):
                cam_slug = camera_entity_id[len("camera."):]
                for suf in CAMERA_RESOLUTION_CHANNEL_SUFFIXES:
                    if cam_slug.endswith(suf):
                        cam_slug = cam_slug[: -len(suf)]
                        break
                cam_stem = cam_slug
            stems: list[str] = []
            for raw in (stem, cam_stem):
                if not raw:
                    continue
                aliased = EXTERIOR_CAMERA_KEY_ALIASES.get(raw, raw)
                for s in (raw, aliased):
                    if s and s not in stems:
                        stems.append(s)
            seen_out = {eid for eid, _ in out}
            for s in stems:
                for probe, tag in (
                    (f"binary_sensor.{s}_person_detected", "legacy"),
                    (f"binary_sensor.{s}_person_detected_2", "legacy2"),
                ):
                    if probe in seen_out:
                        continue
                    try:
                        if self._entity_exists(probe):
                            out.append((probe, tag))
                            seen_out.add(probe)
                    except Exception:  # noqa: BLE001
                        pass
        # Legacy family derivation for vehicle/animal fallback: reuse
        # the retired-shape suffix search inline (no separate helper —
        # this is the exceptional kill-switch-off path).
        if family in ("vehicle", "animal") and base_bs.startswith("binary_sensor."):
            suffixes = (EXTERIOR_VEHICLE_SENSOR_SUFFIXES if family == "vehicle"
                        else EXTERIOR_ANIMAL_SENSOR_SUFFIXES)
            base = base_bs[len("binary_sensor."):]
            stem = base
            for p in ("_person_occupancy", "_person_detected", "_person"):
                if base.endswith(p):
                    stem = base[: -len(p)]
                    break
            for suf in suffixes:
                cand = f"binary_sensor.{stem}{suf}"
                try:
                    if self._entity_exists(cand):
                        out.append((cand, "legacy"))
                        cand2 = f"{cand}_2"
                        if self._entity_exists(cand2):
                            out.append((cand2, "legacy2"))
                        break
                except Exception:  # noqa: BLE001
                    pass
        return out

    def leg_firing_stats(self) -> dict[str, dict[str, Any]]:
        """Return per-camera engine table + sole-firing ratios.

        Shape (dashboard-friendly):
          {
            "<camera_key>": {
              "engines": ["frigate", "frigate2", "protect", ...],
              "fire_counts_by_engine": {"frigate": 12, ...},
              "sole_firing_counts_by_engine": {"frigate": 1, ...},
              "sole_firing_ratio_by_engine": {"frigate": 0.083, ...},
            }, ...
          }

        Observability-only — the "accused-witness" signal for engine
        reliability (cycle-3 scope note). Never gates dispatch.
        """
        cameras: dict[str, dict[str, Any]] = {}
        for (cam, engine), count in self._leg_fire_counts.items():
            entry = cameras.setdefault(cam, {
                "engines": [],
                "fire_counts_by_engine": {},
                "sole_firing_counts_by_engine": {},
                "sole_firing_ratio_by_engine": {},
            })
            if engine not in entry["engines"]:
                entry["engines"].append(engine)
            entry["fire_counts_by_engine"][engine] = count
        for (cam, engine), sole in self._leg_sole_fire_counts.items():
            entry = cameras.setdefault(cam, {
                "engines": [engine],
                "fire_counts_by_engine": {},
                "sole_firing_counts_by_engine": {},
                "sole_firing_ratio_by_engine": {},
            })
            entry["sole_firing_counts_by_engine"][engine] = sole
            total = entry["fire_counts_by_engine"].get(engine, 0) or 1
            entry["sole_firing_ratio_by_engine"][engine] = round(sole / total, 3)
        for entry in cameras.values():
            entry["engines"].sort()
        return cameras

    def _record_leg_fire(self, entity_id: str) -> None:
        """Increment per-(camera, engine) counters + sole-firing decision.

        Called from _on_perimeter_event on every rising edge that passes
        the boot-settle gate. Bounded per-camera recent-fires list keeps
        memory constant. Fails silent on any registry / dict error.
        """
        try:
            engine = self._sensor_engine.get(entity_id)
            cam_key = self._camera_key_for_sensor(entity_id)
            if not engine or not cam_key:
                return
            now = dt_util.now()
            self._leg_fire_counts[(cam_key, engine)] = (
                self._leg_fire_counts.get((cam_key, engine), 0) + 1
            )
            recent = self._recent_fires.setdefault(cam_key, [])
            # Prune stale + bound size.
            cutoff = now.timestamp() - self._SOLE_FIRE_WINDOW_S
            recent = [(e, t) for (e, t) in recent if t.timestamp() >= cutoff][-32:]
            other_engines = {e for (e, _t) in recent if e != engine}
            # F14 (cycle-3 fix-up 2026-08-07): only increment the sole
            # counter ONCE per sole EPISODE. If the previous fire in the
            # window is same-engine, this is a continuation of the same
            # sole episode — do not double-count.
            same_engine_recent = any(e == engine for (e, _t) in recent)
            recent.append((engine, now))
            self._recent_fires[cam_key] = recent
            if not other_engines and not same_engine_recent:
                self._leg_sole_fire_counts[(cam_key, engine)] = (
                    self._leg_sole_fire_counts.get((cam_key, engine), 0) + 1
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PerimeterAlertManager: _record_leg_fire failed", exc_info=True,
            )

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
                # Cycle-3 resolver-legs (2026-08-07): late-registered
                # person legs from ANY integration (frigate `_2`, protect
                # base/`_2`, native AI) picked up via resolver.
                for leg in self._resolve_legs(cam_entity_id, "person"):
                    if leg.entity_id in existing:
                        continue
                    self._sensor_to_camera[leg.entity_id] = cam_entity_id
                    self._sensor_platforms[leg.entity_id] = leg.integration or ""
                    self._sensor_engine[leg.entity_id] = leg.engine
                    self._unsub_perimeter.append(
                        async_track_state_change_event(
                            self.hass, [leg.entity_id],
                            lambda ev: self._on_perimeter_event(ev),
                        )
                    )
                    existing.add(leg.entity_id)
                    _LOGGER.info(
                        "PerimeterAlertManager: late-registered person "
                        "leg %s (engine=%s) subscribed post-HA_STARTED.",
                        leg.entity_id, leg.engine,
                    )
                # Vehicle / animal logged only — closures set at
                # async_setup; operator reload picks them up live.
                for leg in self._resolve_legs(cam_entity_id, "vehicle"):
                    if leg.entity_id not in existing:
                        added_vehicle.append(leg.entity_id)
                for leg in self._resolve_legs(cam_entity_id, "animal"):
                    if leg.entity_id not in existing:
                        added_animal.append(leg.entity_id)
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

    # RETIRED 2026-08-07 (cycle-3 resolver-legs):
    #   _fused_sibling(), _protect_person_legs(), _derive_sibling_sensor()
    # — three generations of hand-rolled slug logic (fused-sibling `_2`
    # probe, protect-legs stem+alias probe, vehicle/animal suffix
    # derivation) replaced wholesale by
    # CameraResolver.resolve_detection_legs() (see _resolve_legs above).
    # These names are asserted ABSENT by
    # quality/tests/test_resolver_legs.py's retirement anchors — do not
    # add methods with these names to this class. The sensor-side
    # dedup + camera-key cooldown/in-flight collapse machinery
    # (_camera_key_for_sensor, _last_alert, _dispatch_in_flight) stays.

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

    # ------------------------------------------------------------------
    # SNAP-1: at-detection local-file snapshot capture + retention
    # ------------------------------------------------------------------

    async def _async_setup_snapshot_dir(self) -> None:
        """Create the snapshot dir and assert privacy + allowed-path.

        Auto-engages the kill switch on ANY failure. Never raises.
        """
        try:
            dir_path = PERIMETER_SNAPSHOT_DIR
            # Privacy invariant: never write under `hass.config.path("www")`
            # (anonymously web-served). D4 load-bearing check.
            www_path = None
            try:
                www_path = self.hass.config.path("www")
            except Exception:  # noqa: BLE001
                www_path = None
            if www_path:
                www_abs = os.path.abspath(www_path)
                dir_abs = os.path.abspath(dir_path)
                if (
                    dir_abs == www_abs
                    or dir_abs.startswith(www_abs + os.sep)
                ):
                    self._snapshot_kill_legacy_url = True
                    _LOGGER.error(
                        "SNAP-1: snapshot dir %s is under HA www path %s "
                        "— refusing to write (web-served privacy "
                        "invariant). Engaging legacy URL fallback.",
                        dir_abs, www_abs,
                    )
                    return

            # Try executor-jobbed mkdir; fall back to sync if the hass
            # test double doesn't provide an awaitable executor helper
            # (test fixtures often use MagicMock — we still want the dir
            # to exist so isolation tests pass; production path always
            # uses the executor).
            try:
                await self.hass.async_add_executor_job(
                    os.makedirs, dir_path, 0o755, True,
                )
            except TypeError:
                os.makedirs(dir_path, 0o755, exist_ok=True)

            allowed = True
            try:
                allowed = bool(
                    self.hass.config.is_allowed_path(dir_path)
                )
            except Exception:  # noqa: BLE001
                allowed = False
            if not allowed:
                self._snapshot_kill_legacy_url = True
                if not self._snapshot_setup_error_logged:
                    _LOGGER.error(
                        "SNAP-1: snapshot dir %s is not an HA allowed_path "
                        "— WhatsApp media_path delivery would be refused. "
                        "Engaging legacy URL fallback. Configure `media_dirs`"
                        " so this path is admitted.",
                        dir_path,
                    )
                    self._snapshot_setup_error_logged = True
                return

            # Discover Frigate instance ids (best-effort, from loaded
            # config entries; empty when frigate integration is absent
            # or single-instance — default URL shape covers that case).
            try:
                self._frigate_instance_ids = (
                    self._discover_frigate_instance_ids()
                )
            except Exception:  # noqa: BLE001
                self._frigate_instance_ids = []

            _LOGGER.info(
                "SNAP-1: snapshot dir ready at %s (allowed_path=True, "
                "kill_legacy_url=%s, frigate_instances=%d)",
                dir_path, self._snapshot_kill_legacy_url,
                len(self._frigate_instance_ids),
            )
        except Exception:  # noqa: BLE001
            self._snapshot_kill_legacy_url = True
            if not self._snapshot_setup_error_logged:
                _LOGGER.error(
                    "SNAP-1: snapshot dir setup failed — engaging legacy "
                    "URL fallback.", exc_info=True,
                )
                self._snapshot_setup_error_logged = True

    def _discover_frigate_instance_ids(self) -> list[str]:
        """Return list of MQTT client_ids for loaded frigate integrations.

        Instance id derivation matches the frigate custom_component's
        own get_frigate_instance_id() (views.py:60-68) — MQTT client_id
        from `hass.data['frigate'][entry_id]['config']['mqtt']['client_id']`.
        Fails-silent to [] (single-instance / not installed / fixture).
        """
        out: list[str] = []
        try:
            frigate_data = self.hass.data.get("frigate", {}) or {}
            for entry_id, blob in frigate_data.items():
                try:
                    cfg = (blob or {}).get("config") or {}
                    client_id = (cfg.get("mqtt") or {}).get("client_id")
                    if client_id and client_id not in out:
                        out.append(str(client_id))
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            return []
        return out

    async def _capture_at_detection_snapshot(
        self, sensor_entity_id: str,
    ) -> str | None:
        """Capture an at-detection snapshot for a perimeter sensor.

        Returns the absolute local path on success, or None on any
        failure (delivery degrades to no-image; alert is never
        blocked). ONE file per collapsed camera key per alert —
        secondary engines that fire within cooldown are dropped by the
        existing camera-key `_dispatch_in_flight` collapse.

        Tiered per PERIMETER_SNAPSHOT_ENGINE_PRECEDENCE:
          1. frigate_event — HTTP GET the stored EVENT snapshot from
             the frigate notification proxy (best-scoring frame OF the
             event; NOT a live grab). Instance-aware.
          2. protect_thumb — UniFi Protect smart-detect event thumbnail.
             VERIFIED 2026-08-08 as NOT VIABLE at the detection edge and
             deliberately falls through to (3):
               - No registered service, no `image` platform, and no
                 camera-entity attribute expose thumbnail bytes.
                 `services.yaml` declares no thumbnail service; the smart-
                 detect binary sensors expose only `event_id`/`event_score`
                 (`homeassistant/components/unifiprotect/entity.py:461-466`).
               - The only byte-returning API is
                 `data.api.get_event_thumbnail(event_id, ...)` reached via
                 the integration's private `async_get_data_for_nvr_id`
                 (`views.py:17, 145, 205-207`) — internal, unstable.
               - Even accepting the private API, the thumbnail is
                 asynchronous. The integration itself buffers with a
                 timer waiting for `EventDetectedThumbnail` messages
                 over WS (`event.py:258-302`); at the moment
                 `binary_sensor.*_person_detected` transitions ON,
                 `get_event_thumbnail` will typically return None
                 (`views.py:211-212` → 404). Marginal benefit over
                 `live_grab` on the same camera does not pay for the
                 private-API ingredient risk.
             Revisit trigger: HA core exposes a stable public API that
             returns thumbnail bytes AND a mechanism to wait for the
             thumbnail to become available, OR live_grab is measured
             to consistently miss the subject.
          3. live_grab — `camera.snapshot` service on the mapped
             camera entity at the rising edge (native Reolink /
             Amcrest / Dahua / anything without an event API).
        """
        if self._snapshot_kill_legacy_url:
            return None
        cam_key = self._camera_key_for_sensor(sensor_entity_id) or ""
        camera_entity_id = self._sensor_to_camera.get(sensor_entity_id, "")
        platform = self._sensor_platforms.get(sensor_entity_id, "")
        now_ts = int(_time.time())

        # --- Precedence: frigate_event -------------------------------
        if "frigate_event" in PERIMETER_SNAPSHOT_ENGINE_PRECEDENCE:
            path = await self._try_capture_frigate_event(
                cam_key, camera_entity_id, platform, now_ts,
            )
            if path:
                return path

        # --- Precedence: protect_thumb (UNVERIFIED on this install) --
        # Falls through — see SNAP-1-followup-protect-thumb.

        # --- Precedence: live_grab -----------------------------------
        if "live_grab" in PERIMETER_SNAPSHOT_ENGINE_PRECEDENCE:
            path = await self._try_capture_live_grab(
                cam_key, camera_entity_id, now_ts,
            )
            if path:
                return path
        return None

    async def _try_capture_frigate_event(
        self, cam_key: str, camera_entity_id: str,
        platform: str, now_ts: int,
    ) -> str | None:
        """Download the stored Frigate event snapshot to a local file."""
        # Fresh event id (existing TTL logic).
        cached = self._frigate_last_event_id.get(
            (cam_key or "").strip().lower()
        )
        if not cached:
            return None
        eid, ts = cached
        try:
            age = (dt_util.utcnow() - ts).total_seconds()
        except Exception:  # noqa: BLE001
            return None
        if not (0 <= age < FRIGATE_SNAPSHOT_ID_TTL_S):
            return None

        # Build candidate URL paths (instance-aware). Default shape
        # first, then each discovered instance id. This subsumes
        # FRIG2SNAP-1 — a frigate2-hosted camera can now resolve a
        # snapshot instead of receiving the default-instance-only URL
        # that today's code builds.
        candidates: list[str] = []
        learned = self._camera_frigate_instance.get(cam_key)
        if learned:
            candidates.append(
                f"/api/frigate/{learned}/notifications/{eid}/snapshot.jpg"
            )
        candidates.append(f"/api/frigate/notifications/{eid}/snapshot.jpg")
        for inst in self._frigate_instance_ids:
            u = f"/api/frigate/{inst}/notifications/{eid}/snapshot.jpg"
            if u not in candidates:
                candidates.append(u)

        for url_path in candidates:
            data = await self._http_get_bytes(url_path)
            if not data:
                continue
            # Learn instance if the successful URL was instance-scoped.
            if url_path.startswith("/api/frigate/") and "notifications" in url_path:
                parts = url_path.split("/")
                if len(parts) >= 4 and parts[3] != "notifications":
                    self._camera_frigate_instance[cam_key] = parts[3]
            file_path = os.path.join(
                PERIMETER_SNAPSHOT_DIR,
                f"{cam_key or 'camera'}_{eid}.jpg",
            )
            if await self._write_snapshot_file(file_path, data, "frigate_event"):
                return file_path
        return None

    async def _try_capture_live_grab(
        self, cam_key: str, camera_entity_id: str, now_ts: int,
    ) -> str | None:
        """Call `camera.snapshot` service on the mapped camera."""
        if not camera_entity_id:
            return None
        file_path = os.path.join(
            PERIMETER_SNAPSHOT_DIR,
            f"{cam_key or 'camera'}_{now_ts}.jpg",
        )
        try:
            await self.hass.services.async_call(
                "camera", "snapshot",
                {
                    "entity_id": camera_entity_id,
                    "filename": file_path,
                },
                blocking=True,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "SNAP-1: camera.snapshot failed for %s",
                camera_entity_id, exc_info=True,
            )
            return None
        # Verify file was written; capture size for ledger.
        try:
            size = await self.hass.async_add_executor_job(
                self._stat_size, file_path,
            )
        except Exception:  # noqa: BLE001
            size = 0
        if not size:
            return None
        self._note_capture(cam_key, file_path, "live_grab", size)
        await self._async_prune_snapshot_dir()
        return file_path

    @staticmethod
    def _stat_size(path: str) -> int:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    async def _http_get_bytes(self, url_path: str) -> bytes | None:
        """HTTP GET a relative HA URL, return bytes or None on failure."""
        abs_url = self._absolutize(url_path)
        if not abs_url:
            return None
        try:
            from homeassistant.helpers.aiohttp_client import (
                async_get_clientsession,
            )
            session = async_get_clientsession(self.hass)
            async with session.get(abs_url) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "SNAP-1: http GET %s failed", abs_url, exc_info=True,
            )
            return None

    async def _write_snapshot_file(
        self, file_path: str, data: bytes, engine: str,
    ) -> bool:
        """Write bytes to file in executor; record + prune on success."""
        if not data:
            return False
        try:
            def _write():
                with open(file_path, "wb") as fh:
                    fh.write(data)
                return len(data)

            size = await self.hass.async_add_executor_job(_write)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "SNAP-1: write %s failed", file_path, exc_info=True,
            )
            return False
        cam_key = os.path.basename(file_path).split("_")[0]
        self._note_capture(cam_key, file_path, engine, size)
        await self._async_prune_snapshot_dir()
        return True

    def _note_capture(
        self, cam_key: str, file_path: str, engine: str, size: int,
    ) -> None:
        """Record last-capture ledger + emit structured log line (D4)."""
        try:
            self._last_snapshot_capture[cam_key or "camera"] = {
                "path": file_path,
                "engine": engine,
                "wrote_at": dt_util.now().isoformat(),
                "bytes": int(size or 0),
            }
        except Exception:  # noqa: BLE001
            pass
        _LOGGER.info(
            "PerimeterSnapshot: wrote=%s bytes=%d engine=%s",
            file_path, int(size or 0), engine,
        )

    async def _async_prune_snapshot_dir(self) -> None:
        """Prune snapshot dir by age (primary) + count (backstop)."""
        try:
            await self.hass.async_add_executor_job(self._prune_snapshot_dir)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("SNAP-1: prune failed", exc_info=True)

    def _prune_snapshot_dir(self) -> tuple[int, int]:
        """Synchronous prune — executor-jobbed by callers.

        Returns (files_deleted, bytes_freed). Age-primary; count is a
        backstop for pathological bursts.
        """
        dir_path = PERIMETER_SNAPSHOT_DIR
        try:
            names = os.listdir(dir_path)
        except OSError:
            return (0, 0)
        cutoff = _time.time() - PERIMETER_SNAPSHOT_RETENTION_AGE_H * 3600
        files: list[tuple[str, float, int]] = []
        for name in names:
            full = os.path.join(dir_path, name)
            try:
                st = os.stat(full)
                if not (st.st_mode & 0o170000) == 0o100000:
                    # not a regular file
                    continue
                files.append((full, st.st_mtime, st.st_size))
            except OSError:
                continue
        deleted = 0
        freed = 0
        keep: list[tuple[str, float, int]] = []
        for full, mtime, size in files:
            if mtime < cutoff:
                try:
                    os.remove(full)
                    deleted += 1
                    freed += size
                except OSError:
                    pass
            else:
                keep.append((full, mtime, size))
        # Count backstop — oldest first.
        if len(keep) > PERIMETER_SNAPSHOT_RETENTION_COUNT:
            keep.sort(key=lambda t: t[1])
            over = len(keep) - PERIMETER_SNAPSHOT_RETENTION_COUNT
            for full, _mtime, size in keep[:over]:
                try:
                    os.remove(full)
                    deleted += 1
                    freed += size
                except OSError:
                    pass
        if deleted:
            _LOGGER.info(
                "PerimeterSnapshot: prune deleted=%d bytes_freed=%d "
                "(age_h=%d count_cap=%d)",
                deleted, freed,
                PERIMETER_SNAPSHOT_RETENTION_AGE_H,
                PERIMETER_SNAPSHOT_RETENTION_COUNT,
            )
        return (deleted, freed)

    @callback
    def _on_snapshot_sweep_tick(self, _now: Any) -> None:
        """Periodic prune sweep (safety net)."""
        self.hass.async_create_task(self._async_prune_snapshot_dir())

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
        # Cycle-3 resolver-legs: disagreement telemetry — record every
        # rising edge that survived the boot-settle gate. Observability
        # only; never gates dispatch.
        self._record_leg_fire(entity_id)
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

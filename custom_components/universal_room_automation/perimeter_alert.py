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

import asyncio
import logging
import os
import re as _re
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
    CONF_PERIMETER_ALERT_NOTIFY_SERVICE,
    CONF_PERIMETER_ALERT_NOTIFY_TARGET,
    CONF_PERIMETER_VEHICLE_HOURS_START,
    CONF_PERIMETER_VEHICLE_HOURS_END,
    DEFAULT_PERIMETER_VEHICLE_HOURS_START,
    DEFAULT_PERIMETER_VEHICLE_HOURS_END,
    PERIMETER_ALERT_COOLDOWN_SECONDS,
    ENTRY_TYPE_INTEGRATION,
    CONF_ENTRY_TYPE,
    CAMERA_PLATFORM_FRIGATE,
    NM_HAZARD_EXTERIOR_PERSON,
    NM_HAZARD_EXTERIOR_VEHICLE,
    EXTERIOR_CAMERA_KEY_ALIASES,
    NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE,
    NM_HAZARD_EXTERIOR_PERSON_DEFAULT_SEVERITY,
    NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY,
    NM_ROUTE_REASON_ENRICHED,
    NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH,
    PERIMETER_ENRICHMENT_BASE_TEMPLATE_PERSON,
    PERIMETER_ENRICHMENT_BASE_TEMPLATE_VEHICLE,
    CONF_PERIMETER_ENRICHMENT_ENABLED,
    CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS,
    DEFAULT_PERIMETER_ENRICHMENT_ENABLED,
    LLMVISION_ENRICHMENT_KILL,
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
    PERIMETER_SNAPSHOT_CAPTURE_BUDGET_S,
    PERIMETER_SNAPSHOT_HTTP_TIMEOUT_S,
    PERIMETER_SNAPSHOT_EDGE_DEDUP_S,
    PERIMETER_SNAPSHOT_EDGE_TTL_S,
    PERIMETER_SNAPSHOT_EDGE_CAPTURES_MAX,
    PERIMETER_SNAPSHOT_PRUNE_DEBOUNCE_S,
    TRACK_LINK_WINDOW_S,
    PERIMETER_BURST_DEMOTE_ENABLED,
    PERIMETER_BURST_WINDOW_S,
    PERIMETER_BURST_MIN_ALERTS,
    PERIMETER_BURST_NIGHT_ONLY,
    PERIMETER_BURST_NIGHT_WINDOW,
    EXTERIOR_VEHICLE_NIGHT_START,
    EXTERIOR_VEHICLE_NIGHT_END,
    EXTERIOR_VEHICLE_ALERT_STATES,
    EXTERIOR_VEHICLE_ALERT_COOLDOWN_SECONDS,
    EXTERIOR_VEHICLE_SENSOR_SUFFIXES,
    EXTERIOR_ANIMAL_SENSOR_SUFFIXES,
    FACE_NAME_LATCH_TTL_S,
    CONF_PERIMETER_ZONE_SENSORS,
    PERIMETER_FRIGATE_BUS_SILENT_MIN_EDGES,
    PERIMETER_FRIGATE_BUS_WINDOW_S,
    CONF_PERIMETER_ZONE_AGREEMENT_DEMOTE,
    DEFAULT_PERIMETER_ZONE_AGREEMENT_DEMOTE,
    PERIMETER_ZONE_AGREEMENT_MAX_AGE_S,
    CONF_PERIMETER_SINGLE_SOURCE_DEMOTE,
    DEFAULT_PERIMETER_SINGLE_SOURCE_DEMOTE,
    PERIMETER_AGREEMENT_SAVE_DELAY_S,
    PERIMETER_SS_SETTLE_S,
    PERIMETER_SS_MIN_AGREEMENT,
    PERIMETER_SS_MIN_SAMPLES,
    PERIMETER_SS_WINDOW_N,
    CONF_PERIMETER_VLM_GATE,
    DEFAULT_PERIMETER_VLM_GATE,
    PERIMETER_VLM_GATE_SHADOW,
    PERIMETER_VLM_GATE_ENFORCE,
    PERIMETER_VLM_TRUSTED_TIERS,
    CONF_PERIMETER_EGRESS_KNOWN_XCORR_GATE,
    DEFAULT_PERIMETER_EGRESS_KNOWN_XCORR_GATE,
    PERIMETER_EGRESS_IDENTITY_WAIT_S,
    PERIMETER_EGRESS_IDENTITY_MATCH_S,
    PERIMETER_EGRESS_KNOWN_MIN_CONF,
    PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S,
    PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S,
    PERIMETER_EGRESS_XCORR_SETTLE_S,
    CONF_PERIMETER_IDENTITY_FOLLOWUP,
    DEFAULT_PERIMETER_IDENTITY_FOLLOWUP,
    PERIMETER_IDENTITY_FOLLOWUP_WINDOW_S,
    PERIMETER_IDENTITY_FOLLOWUP_POLL_S,
)
from .domain_coordinators.base import Severity
from .domain_coordinators._nm_cycle_a import is_life_safety_hazard  # CIRCLING-LABEL-1: I3 gate uses this
from .perimeter_enrichment import enrich_dispatched_alert, enrich_with_verdict
from .arrival_edges import (
    area_slug_of_entity,
    live_arrival_slug,
    nonface_arrival_source,
)
from .perimeter_fp_gates import (
    AgreementTracker,
    VERDICT_NO,
    nvr_family,
    zone_slug,
)


# CIRCLING-LABEL-1: strict escalation ordering for the
# classification-transition exemption. Unknown / None classes map to -1
# so the I2 predicate (`current_rank <= last_rank -> blocked`) treats an
# unknown-vs-None comparison as blocked (safe). If the classification
# vocabulary ever grows beyond {pass_by, approach, circling}, adding an
# entry here suffices; I2's strict-<= boundary is unchanged.
_CLASSIFICATION_RANK: dict[str, int] = {
    "pass_by": 0,
    "approach": 1,
    "circling": 2,
}


def migrate_consol1_perimeter_keys(
    options: dict,
) -> tuple[dict, bool]:
    """CONSOL-1 §D6 options-migration helper (extracted per fix-up
    C-SN-MIG + A2). Pure function — no I/O, no HA imports beyond the
    module-const key names. Idempotent: new-key-wins when both are
    present.

    Returns (new_options, changed) where `changed` is True iff at least
    one migration action was taken (rename or strip). Callers persist
    the returned dict via `hass.config_entries.async_update_entry` and
    log per-key info messages (kept at the call site, not here, so the
    helper stays log-free and trivially unit-testable).
    """
    _OLD_START = "perimeter_alert_hours_start"
    _OLD_END = "perimeter_alert_hours_end"
    _OLD_SVC = "perimeter_alert_notify_service"
    _OLD_TGT = "perimeter_alert_notify_target"
    _NEW_START = "perimeter_vehicle_hours_start"
    _NEW_END = "perimeter_vehicle_hours_end"
    out = dict(options)
    changed = False
    if _OLD_START in out and _NEW_START not in out:
        out[_NEW_START] = out[_OLD_START]
        changed = True
    if _OLD_END in out and _NEW_END not in out:
        out[_NEW_END] = out[_OLD_END]
        changed = True
    for _k in (_OLD_START, _OLD_END, _OLD_SVC, _OLD_TGT):
        if _k in out:
            out.pop(_k, None)
            changed = True
    return out, changed
# F1 (cycle-3 fix-up): single source of truth for person-family suffix
# vocabulary — perimeter dedup MUST NOT drift from resolver discovery.
from .camera_resolver import _PERSON_SUFFIXES as _RESOLVER_PERSON_SUFFIXES

_LOGGER = logging.getLogger(__name__)

# SNAP-1 fix-up (F2): sanitize any token that will be interpolated into
# a filesystem path or URL. Only allow character classes safe for both:
# ascii letters, digits, dot, underscore, hyphen. os.path.join does
# NOT strip '..' — any attacker-controlled component (Frigate event id
# from the bus, camera name from the resolver) must be filtered here.
_SNAPSHOT_TOKEN_RE = _re.compile(r"[^A-Za-z0-9._\-]")


def _sanitize_snapshot_token(raw: Any, max_len: int = 96) -> str:
    """Return a filesystem-safe token or '' if the input is unusable."""
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    s = _SNAPSHOT_TOKEN_RE.sub("_", s)
    # Collapse any run of dots (>=2) — '..' is the traversal primitive.
    # '.' is preserved singly (needed for '.jpg' extensions).
    s = _re.sub(r"\.{2,}", "_", s)
    # Reject dot-only / leading-dot shapes outright.
    if s in (".", "..") or s.startswith("."):
        s = "_" + s.lstrip(".")
    return s[:max_len]


def _path_within(child: str, parent: str) -> bool:
    """True iff realpath(child) is at-or-under realpath(parent).

    SNAP-1 fix-up (F2 + F3): containment guard for every filesystem
    write, and for the www-privacy setup guard. Uses realpath on both
    sides so symlinks cannot escape the parent directory.
    """
    try:
        child_real = os.path.realpath(child)
        parent_real = os.path.realpath(parent)
    except Exception:  # noqa: BLE001
        return False
    if not parent_real:
        return False
    try:
        common = os.path.commonpath([child_real, parent_real])
    except ValueError:
        # Different drives on Windows; refuse.
        return False
    return common == parent_real

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
        # v5.107.2 Fix C: last ENDED Frigate event id per camera key.
        self._frigate_ended_event_id: dict[str, str] = {}
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
        # XCORR-1: dispatched-alert timestamps per collapsed camera_key.
        # Used by the burst-demotion helper to count prior alerts within
        # PERIMETER_BURST_WINDOW_S. Only successful dispatches are recorded.
        self._recent_alerts_by_camera: dict[str, list[datetime]] = {}
        # XCORR-1: per-camera_key record of the most recent demotion decision
        # (whether or not demotion actually applied). Surfaced via
        # burst_demotion_stats() for the exterior open-tracks diagnostic
        # sensor so the operator can see WHY something was demoted without
        # log-level surgery. Bounded to one entry per camera.
        self._last_burst_decision: dict[str, dict[str, Any]] = {}
        # CIRCLING-SEVERITY-1: per-camera_key record of the most recent
        # PRE-DISPATCH suppression. The burst path records WHY it demoted;
        # the two gates that run BEFORE dispatch (egress suppression and the
        # per-camera cooldown) previously returned silently, so a suppressed
        # track left no evidence of which gate stopped it. That is the exact
        # ambiguity the 2026-09-13 trace isolated and could not resolve from
        # code alone. Same idiom, same surfacing, one entry per camera.
        self._last_suppression: dict[str, dict[str, Any]] = {}
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
        # SNAP-1 fix-up (F1): at-detection edge-capture buffer, keyed by
        # collapsed camera_key. Value: {"task": Task, "started_ts": float
        # (monotonic), "started_at": datetime, "entity_id": str}.
        # The rising-edge callback kicks off capture as a task BEFORE
        # scheduling the handler task; the handler awaits (with budget)
        # and consumes. This is the load-bearing site for the cycle's
        # stated invariant "capture at the sensor edge, not seconds
        # later when handler code runs".
        self._edge_captures: dict[str, dict[str, Any]] = {}
        # SNAP-1 fix-up (F9b): last on-write prune wall-time to debounce
        # the O(N) sweep. Periodic 6h sweep is the age backstop.
        self._last_prune_ts: float = 0.0
        # ---- PERIMETER-FP-STREET-NOISE-1 (v5.107.0) ----------------------
        # D1: zone sensor -> {"camera", "camera_key", "frigate_name",
        # "zone_slug"}; camera entity -> its mapped zone sensors; runtime
        # camera-key overlay (zone stem -> camera key) consulted by
        # _camera_key_for_sensor BEFORE the static alias table. All three
        # are filled before the first _wire_camera call (plan M1).
        self._zone_map: dict[str, dict[str, str]] = {}
        self._zoned_cameras: dict[str, list[str]] = {}
        self._zone_key_overrides: dict[str, str] = {}
        # D5/D10.5: subscribed PERIMETER person legs per collapsed camera key
        # (liveness test reads their states).
        self._person_legs_by_key: dict[str, set[str]] = {}
        # D2: latest Frigate person event per lowercase Frigate camera name
        # + rolling bus / Frigate-edge timestamps per camera.
        self._frigate_event_cache: dict[str, dict[str, Any]] = {}
        self._frigate_bus_times: dict[str, list[float]] = {}
        self._frigate_edge_times: dict[str, list[float]] = {}
        self._frigate_bus_silent_warned: bool = False
        # Gate decisions, one dict per camera key: {gate: decision}.
        self._last_gate_decisions: dict[str, dict[str, Any]] = {}
        # D5: agreement tracker + persistence + timers.
        self._agreement = AgreementTracker(
            PERIMETER_SS_WINDOW_N, self._SOLE_FIRE_WINDOW_S,
        )
        self._agreement_store: Any = None
        self._agreement_load_ok: bool = False
        self._unsub_agreement_timer: Any = None
        # D5 / D10.5 hold timers: cooldown_key -> (unsub, future).
        self._pending_holds: dict[str, tuple[Any, Any]] = {}
        # D10: dual-role (perimeter AND egress) camera entities, and the
        # last egress stamp per egress CAMERA entity.
        self._dual_role_cameras: set[str] = set()
        self._last_egress_time_by_camera: dict[str, datetime] = {}
        # D10.5: recent `ura_person_egress_event` identities per camera key:
        # list of (detection_ts, person_id, identity_confidence).
        self._recent_egress_identity: dict[str, list[tuple[datetime, str, float]]] = {}
        self._unsub_egress_identity: Any = None
        # D10.5 (review B-MED-2): real not_home -> home edges per person slug
        # (epoch seconds), recorded by a live listener; boot replays and
        # transitions inside the post-setup exclusion are ignored.
        self._person_arrivals: dict[str, float] = {}
        self._unsub_person_arrivals: Any = None
        self._fp_setup_ts: float | None = None
        # PERIMETER-IDENTITY-FOLLOWUP-1: at most one pending "that was <name>"
        # follow-up per camera key: {edge, entity_id, severity, elapsed, unsub}.
        self._pending_followups: dict[str, dict[str, Any]] = {}

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

        # CONSOL-1 §D1 — one-shot ERROR log if operator still has the
        # retired legacy notify keys populated. The runtime dispatch no
        # longer honors them; this surfaces the config drift so the
        # operator can clear the keys via options flow.
        try:
            _legacy_service, _legacy_target = self._get_notify_config()
            if _legacy_service or _legacy_target:
                _LOGGER.error(
                    "PerimeterAlertManager: legacy notify keys are "
                    "populated (service=%r, target=%r) but the legacy "
                    "notify leg is RETIRED (CONSOL-1 §D1). Clear "
                    "'perimeter_alert_notify_service' and "
                    "'perimeter_alert_notify_target' in the integration "
                    "options; all dispatch now flows through NM.",
                    _legacy_service, _legacy_target,
                )
        except Exception:  # noqa: BLE001
            pass

        perimeter_infos = self._resolve_camera_infos(CONF_PERIMETER_CAMERAS)
        egress_infos = self._resolve_camera_infos(CONF_EGRESS_CAMERAS)
        # PERIMETER-FP D10: role is derived from both lists (no new knob).
        self._dual_role_cameras = (
            {c for c, _i in perimeter_infos} & {c for c, _i in egress_infos}
        )
        # PERIMETER-FP D1: zone map + key overlay BEFORE any _wire_camera
        # (the F7 tripwire and the linker allowlist derive keys during wiring).
        self._build_zone_map(perimeter_infos)

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
            # PERIMETER-FP D1: one exclusion predicate at EVERY wiring site
            # (base union, resolver legs, `_2` safety net, legacy fallback;
            # _rescan_siblings applies the same predicate post-HA_STARTED).
            _zoned = role == "perimeter" and bool(
                self._zoned_cameras.get(cam_entity_id)
            )

            _dropped_engines: list[str] = []

            def _excluded(eid: str, engine: str) -> bool:
                hit = role == "perimeter" and self._is_excluded_zone_camera_leg(
                    cam_entity_id, eid, engine,
                )
                if hit:
                    _dropped_engines.append(engine)
                return hit
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
                    "protect" if base_bs.endswith("_person_detected") else (
                        # PERIMETER-FP (v5.107.0): a `_2` configured base was
                        # tagged "legacy", hiding its NVR family from the
                        # D5/D10.5 liveness + corroboration checks. Same
                        # `_2` rule as camera_resolver._engine_tag.
                        "frigate2" if base_bs.endswith("_person_occupancy_2") else (
                            "protect2" if base_bs.endswith("_person_detected_2")
                            else "legacy"
                        )
                    )
                )
                if not _excluded(base_bs, base_engine) and _append_sensor(
                    target, seen, base_bs, info.platform or "", cam_entity_id,
                ):
                    legs_found.append(base_engine)
                    engine_by_leg[base_bs] = base_engine
                for leg in resolver_legs:
                    plat = leg.integration or ""
                    if not _excluded(leg.entity_id, leg.engine) and _append_sensor(
                        target, seen, leg.entity_id, plat, cam_entity_id,
                    ):
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
                        if not _excluded(sibling, _e2) and _append_sensor(
                            target, seen, sibling, info.platform or "", cam_entity_id,
                        ):
                            legs_found.append(_e2)
                            engine_by_leg[sibling] = _e2
                    elif (
                        not self._entity_exists(sibling)
                        and role == "perimeter"
                        and not _zoned  # D1 item 7: zone leg IS the Frigate leg
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
                # TEST-1 (shadow diff): the resolver path is now live, but
                # the retired helpers it replaced could surface a leg it
                # does not. Compute what the LEGACY fallback WOULD have
                # found and WARN if the resolver's leg set is not a
                # superset — a live tripwire for silent coverage shrinkage
                # that unit tests miss (the reason this card exists: we
                # gave a hardened surface new methods; something is bound
                # to fail). Observability only — does NOT change the legs
                # actually subscribed (the resolver set already won above);
                # the union with base+`_2` above is the belt-and-braces.
                self._warn_if_not_leg_superset(
                    cam_entity_id, base_bs, "person", set(seen),
                )
            else:
                # Legacy fallback path (kill switch OFF / no manager).
                for eid, engine in self._legacy_leg_fallback(base_bs, cam_entity_id, "person"):
                    if not _excluded(eid, engine) and _append_sensor(
                        target, seen, eid, info.platform or "", cam_entity_id,
                    ):
                        legs_found.append(engine)
                        engine_by_leg[eid] = engine
                if (
                    role == "perimeter"
                    and not _zoned
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
            # PERIMETER-FP D1 item 3: the mapped zone sensors replace the
            # camera's Frigate person legs. Engine tag: a zone lives on the
            # SAME Frigate host as the camera leg it replaces, so it inherits
            # that leg's tag (live zones are bare-named but Frigate-2 sourced:
            # tagging them by the `_2` suffix alone would mislabel them
            # "frigate"); with nothing dropped, fall back to the `_2` rule.
            if _zoned:
                _host2 = "frigate2" in _dropped_engines
                for _zs in self._zoned_cameras.get(cam_entity_id, []):
                    _zeng = "frigate2" if (_host2 or _zs.endswith("_2")) else "frigate"
                    if _append_sensor(
                        target, seen, _zs, CAMERA_PLATFORM_FRIGATE, cam_entity_id,
                    ):
                        legs_found.append(_zeng)
                        engine_by_leg[_zs] = _zeng
                _LOGGER.info(
                    "PerimeterAlertManager: perimeter camera %s Frigate leg "
                    "is zone sensor(s) %s (camera-level Frigate legs dropped)",
                    cam_entity_id, self._zoned_cameras.get(cam_entity_id),
                )
            # Record engine tags for the disagreement telemetry.
            self._sensor_engine.update(engine_by_leg)
            # PERIMETER-FP D5/D10.5: person legs per camera key (liveness).
            if role == "perimeter":
                for _eid in engine_by_leg:
                    _ck = self._camera_key_for_sensor(_eid) or _eid
                    self._person_legs_by_key.setdefault(_ck, set()).add(_eid)
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
                        # v5.62.1: this early return used to be SILENT, which is
                        # exactly what hid the READY-dispatch-before-registration
                        # ordering bug — the handler ran, found no linker, and
                        # said nothing, so the SECC-1 sanity WARNING never fired
                        # either. A guard that can no-op must say so.
                        _LOGGER.warning(
                            "PerimeterAlertManager: READY handler fired but "
                            "cannot install allowlist (linker_present=%s, "
                            "cameras_staged=%d) — allowlist NOT installed",
                            _lk is not None,
                            len(self._perimeter_allowlist or ()),
                        )
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
                    # PERIMETER-FP D10.1: per-camera stamp for the role-aware
                    # gate (the global stamp above is unchanged).
                    self._note_egress_stamp(
                        event.data.get("entity_id", ""), self._last_egress_time,
                    )
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
                # PERIMETER-FP D2: richer per-camera record + bus counter.
                # Observability + D3 input only; the id cache below is
                # unchanged (snapshot readers depend on it).
                self._note_frigate_event(cam_key, msg_type, after)
                if msg_type == "end":
                    # v5.107.2 Fix C: remember the ended id (do NOT erase
                    # the cache — the NM URL path still wants it). SNAP-1
                    # edge capture refuses an ended id: at a new rising
                    # edge an already-ended event is the PREVIOUS track.
                    if event_id:
                        self._frigate_ended_event_id[cam_key] = str(event_id)
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

        # PERIMETER-FP D10.5: cache egress identities (only consumed for
        # dual-role cameras' own alerts). Listener exists only when such a
        # camera is configured, so today's install registers nothing.
        if self._dual_role_cameras:
            @callback
            def _on_egress_identity(event: Event) -> None:
                self._note_egress_identity(event.data or {})

            self._unsub_egress_identity = self.hass.bus.async_listen(
                "ura_person_egress_event", _on_egress_identity,
            )
            # Arrival edges for the face+non-face rule. The edge rule is the
            # shared arrival_edges module (also used by the SC lock regime's
            # camera_face gate); this listener + `_person_arrivals` stay
            # here so boot exclusion is timed from perimeter setup.
            self._fp_setup_ts = dt_util.now().timestamp()
            _persons = [f"person.{s}" for s in self._tracked_person_slugs()]
            if _persons:
                self._unsub_person_arrivals = async_track_state_change_event(
                    self.hass, _persons, self._on_person_arrival_event,
                )

        # PERIMETER-FP D5: load the persisted agreement tracker.
        await self._async_load_agreement()

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
            # PERIMETER-FP D10.3 (rev 2, M7): dual-role cameras get NO
            # vehicle legs until PERIMETER-EGRESS-VEHICLE-ANIMAL-1 decides.
            # Animal legs stay (they only feed the linker).
            _dual = cam_entity_id in self._dual_role_cameras
            v_legs = [] if _dual else self._resolve_legs(cam_entity_id, "vehicle")
            a_legs = self._resolve_legs(cam_entity_id, "animal")
            if not v_legs and base_bs and not _dual:
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
                    # SNAP-1 fix-up (F6): capture at the vehicle rising
                    # edge too — deep-night vehicle alerts must also
                    # ride an at-detection frame.
                    self._maybe_start_edge_capture(ent)
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

        # PERIMETER-FP D5/D10.5: discharge every pending hold (the waiting
        # handler wakes, sees `_active` False and drops its dispatch), the
        # agreement timer and the egress identity listener.
        self._active = False
        for _k, (_unsub, _fut) in list(self._pending_holds.items()):
            try:
                _unsub()
            except Exception:  # noqa: BLE001
                pass
            try:
                if _fut is not None and not _fut.done():
                    _fut.set_result(None)
            except Exception:  # noqa: BLE001
                pass
        self._pending_holds.clear()
        if self._unsub_agreement_timer is not None:
            try:
                self._unsub_agreement_timer()
            except Exception:  # noqa: BLE001
                pass
            self._unsub_agreement_timer = None
        if self._unsub_egress_identity is not None:
            try:
                self._unsub_egress_identity()
            except Exception:  # noqa: BLE001
                pass
            self._unsub_egress_identity = None
        if self._unsub_person_arrivals is not None:
            try:
                self._unsub_person_arrivals()
            except Exception:  # noqa: BLE001
                pass
            self._unsub_person_arrivals = None
        # PERIMETER-IDENTITY-FOLLOWUP-1: discharge every pending follow-up.
        for _fk in list(self._pending_followups):
            self._cancel_identity_followup(_fk, "teardown")
        # D5 (review B-LOW-3): flush finalised agreement outcomes now so a
        # reload's new manager does not load a store 30 s stale.
        if self._agreement_store is not None:
            try:
                await self._agreement_store.async_save(self._agreement.to_dict())
            except Exception:  # noqa: BLE001
                _LOGGER.debug("PerimeterAlertManager: agreement flush failed",
                              exc_info=True)

        # SNAP-1 fix-up (F1): cancel any in-flight edge-capture tasks.
        for _key, _entry in list(self._edge_captures.items()):
            try:
                t = _entry.get("task")
                if t is not None and not t.done():
                    t.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._edge_captures.clear()

        self._active = False
        _LOGGER.debug("PerimeterAlertManager: torn down")

    async def _async_handle_perimeter_trigger(self, entity_id: str) -> None:
        """Evaluate a perimeter person detection and escalate if warranted."""
        now = dt_util.now()

        # --- 1. (CONSOL-1 §D2) Alert-hours existence gate REMOVED for the
        # person path. Severity is contextual (see §6 / D2 contextual
        # severity function). Vehicle path retains its own window via
        # _is_in_vehicle_alert_hours at :2041 (§D6, renamed keys).

        # --- 2. Check egress suppression window ---
        # PERIMETER-FP D10.1 (INV-EGRESS-SELF): a dual-role camera ignores
        # stamps from every dual-role camera; others see the global stamp.
        _egress_ts = self._egress_stamp_for(entity_id)
        if _egress_ts is not None:
            seconds_since_egress = (now - _egress_ts).total_seconds()
            if seconds_since_egress <= EGRESS_SUPPRESSION_WINDOW_SECONDS:
                _LOGGER.debug(
                    "PerimeterAlertManager: alert suppressed — egress crossing "
                    "%.0fs ago (within %ds window)",
                    seconds_since_egress,
                    EGRESS_SUPPRESSION_WINDOW_SECONDS,
                )
                # CIRCLING-SEVERITY-1: record WHY before returning.
                self._record_suppression(
                    self._camera_key_for_sensor(entity_id) or entity_id,
                    "egress_suppression",
                    seconds_since_egress=round(seconds_since_egress, 1),
                    window_s=int(EGRESS_SUPPRESSION_WINDOW_SECONDS),
                )
                return

        # --- 3. Check per-camera cooldown (outer, authoritative rate limit) ---
        # Cycle 2 (fused-sourcing dedup): key by camera, not sensor entity_id,
        # so an event visible on both the F1 base sensor and the F2 `_2`
        # sibling still consumes ONE cooldown slot -> ONE alert.
        cooldown_key = self._camera_key_for_sensor(entity_id) or entity_id
        last_alert = self._last_alert.get(cooldown_key)
        # CIRCLING-LABEL-1: two-step gate. Cooldown check first; if it
        # would block, offer the classification-transition exemption
        # exactly once per (track × target-class) — see helper docstring
        # for invariants I1-I4. `exemption_active` is threaded into
        # XCORR-1 (D5b) so the exemption's transition dispatch cannot be
        # burst-demoted away.
        # B-LOW-1: `exempted_class` is the seeded target class when the
        # exemption fires. Rollback discards it if this flow does NOT
        # reach a successful NM dispatch.
        exempted_class: str | None = None
        if last_alert is not None:
            seconds_since_alert = (now - last_alert).total_seconds()
            if seconds_since_alert < PERIMETER_ALERT_COOLDOWN_SECONDS:
                exempted_class = self._classification_transition_exemption_permitted(
                    cooldown_key=cooldown_key,
                    entity_id=entity_id,
                    now=now,
                )
                if exempted_class is None:
                    _LOGGER.debug(
                        "PerimeterAlertManager: alert suppressed for %s — "
                        "cooldown (%.0fs of %ds elapsed, no "
                        "classification-transition exemption)",
                        entity_id,
                        seconds_since_alert,
                        PERIMETER_ALERT_COOLDOWN_SECONDS,
                    )
                    # CIRCLING-SEVERITY-1: the exemption WAS offered and
                    # declined here — that distinction is the discriminator.
                    self._record_suppression(
                        cooldown_key,
                        "cooldown",
                        seconds_since_alert=round(seconds_since_alert, 1),
                        cooldown_s=int(PERIMETER_ALERT_COOLDOWN_SECONDS),
                        exemption_offered=True,
                        exemption_granted=False,
                    )
                    return
                _LOGGER.info(
                    "PerimeterAlertManager: cooldown bypassed for %s by "
                    "classification-transition exemption",
                    entity_id,
                )
        exemption_active = exempted_class is not None

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
            # B-LOW-1: S4 suppressed us BEFORE dispatch — undo the
            # optimistic exemption seed so the ledger slot is available
            # for a future legitimate escalating hop.
            self._rollback_transition_exemption(
                cooldown_key=cooldown_key, cls=exempted_class, now=now,
            )
            return

        # --- 3b. Redesign (Tier 3 fix-up): NO same-track suppression path.
        # Every event that passes the per-camera cooldown gate DISPATCHES.
        # Same-track continuations may be severity-DEMOTED (only when
        # CONFIDENT) or ESCALATED (approach/circling); they are never
        # silenced. INV-XT reduces to "≤ 1 dispatch per camera per cooldown"
        # which is exactly INV-XP — no separate silencing gate.

        # --- 4. Resolve severity from house state (D2 contextual, fail-safe) ---
        # C-mut-d: if the resolver itself raises, fall back to CRITICAL so
        # the docstring guarantee ("any exception → CRITICAL") holds even
        # if a downstream helper is broken.
        _cam_class_early = self._camera_class_for_sensor(entity_id)
        _track_class_early: str | None = None
        try:
            _linker_early = self.hass.data.get(DOMAIN, {}).get(
                "exterior_track_linker"
            )
            _cam_key_early = self._camera_key_for_sensor(entity_id)
            if _linker_early is not None and _cam_key_early:
                _t = _linker_early.find_owning_track(
                    _cam_key_early, "person", now,
                )
                if _t is not None:
                    _track_class_early = _linker_early.classify(_t)
        except Exception:  # noqa: BLE001
            _track_class_early = None
        try:
            severity = self._severity_for_current_house_state(
                camera_class=_cam_class_early,
                track_class=_track_class_early,
            )
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

        # --- 4c. XCORR-1: burst-demotion for isolated single-camera alerts.
        # Runs AFTER severity-map coercion so the map's escalation on
        # approach/circling can still raise; we only DEMOTE (floor at LOW).
        # Composes with, does not bypass, the demote-never-silence
        # invariant (INV-XP): the alert always dispatches.
        try:
            should_demote, burst_decision = self._evaluate_burst_demotion(
                cooldown_key, entity_id, now,
                exemption_active=exemption_active,
            )
            burst_decision["severity_before"] = severity.name
            if should_demote:
                new_sev = max(Severity.LOW, min(severity, Severity.LOW))
                if new_sev != severity:
                    _LOGGER.info(
                        "PerimeterAlertManager: severity DEMOTED %s→%s "
                        "(XCORR-1 burst: camera=%s, prior_alerts=%d/%ds, "
                        "sibling_corroborated=%s, adjacent_activity=%s)",
                        severity.name, new_sev.name, cooldown_key,
                        burst_decision["prior_alerts_in_window"],
                        int(PERIMETER_BURST_WINDOW_S),
                        burst_decision["sibling_corroborated"],
                        burst_decision["adjacent_activity"],
                    )
                    severity = new_sev
            burst_decision["severity_after"] = severity.name
            self._last_burst_decision[cooldown_key] = burst_decision
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PerimeterAlertManager: XCORR-1 burst-demote evaluation "
                "raised — keeping today's severity (fail-open).",
                exc_info=True,
            )

        # --- 4d. PERIMETER-FP gates (demote-only, floor LOW, never silence).
        # D3 zone agreement, then D5 single-source OR (dual-role camera)
        # D10.5 known/xcorr. D5/D10.5 may HOLD the in-flight key across a
        # bounded settle; `_held` tracks that so every exit releases it.
        severity = self._apply_zone_agreement_gate(
            cooldown_key, entity_id, now, severity, exemption_active,
        )
        _held = False
        if self._is_dual_role_sensor(entity_id):
            severity, _held, _proceed = await self._apply_egress_identity_gate(
                cooldown_key, entity_id, now, severity, exemption_active,
            )
        else:
            severity, _held, _proceed = await self._apply_single_source_gate(
                cooldown_key, entity_id, now, severity, exemption_active,
            )
        if not _proceed:
            # Teardown / HA stopping during a hold: drop, as at :_do_dispatch.
            if _held:
                self._dispatch_in_flight.discard(cooldown_key)
            self._rollback_transition_exemption(
                cooldown_key=cooldown_key, cls=exempted_class, now=now,
            )
            return
        try:
            await self._async_finish_perimeter_dispatch(
                entity_id=entity_id, now=now, severity=severity,
                cooldown_key=cooldown_key, exempted_class=exempted_class,
                exemption_active=exemption_active, held=_held,
            )
        except BaseException:
            if _held:
                self._dispatch_in_flight.discard(cooldown_key)
            raise

    async def _async_finish_perimeter_dispatch(
        self, *, entity_id: str, now: datetime, severity: Severity,
        cooldown_key: str, exempted_class: str | None,
        exemption_active: bool, held: bool,
    ) -> None:
        """Snapshot -> message -> enrichment (+D6) -> dispatch.

        Body moved verbatim from `_async_handle_perimeter_trigger` (v5.107.0)
        so a D5/D10.5 hold can be released on any exception path.
        """

        # --- 5. Resolve snapshot URL (D4) ---
        snapshot_url, delay_s = self._resolve_snapshot_url_and_delay(entity_id)
        # SNAP-1: capture an at-detection snapshot to a LOCAL FILE (best
        # effort). When kill switch is engaged (const, or setup-time
        # assertion failure) this returns None and delivery keeps the
        # legacy URL shape byte-for-byte. Capture time is decoupled
        # from cooldown/dispatch/llmvision-delay because it runs BEFORE
        # the scheduler delay below — the operator's core requirement.
        # A capture failure NEVER blocks the alert.
        # SNAP-1 fix-up (F1+F7): consume the EDGE-initiated capture
        # (started in _on_perimeter_event before this handler was
        # scheduled). Fall back to inline capture only when no edge
        # entry is present. The kill-switch check lives in ONE place
        # (`_capture_at_detection_snapshot` and `_maybe_start_edge_capture`)
        # so there is no duplicate-guard hollow-test surface here.
        snapshot_path = await self._await_edge_capture(entity_id)
        # SNAP-1: when we successfully captured a local file, delay is 0
        # (the file is already at-detection; no reason to defer for a
        # subsequent live-fallback grab). Preserve delay for the URL
        # fallback path — that keeps CONF_EXTERIOR_SNAPSHOT_OFFSET_S
        # semantics unchanged.
        if snapshot_path:
            delay_s = 0

        # --- 6. Dispatch (NM only; CONSOL-1 §D1 — legacy leg RETIRED).
        # `_async_send_legacy_notification` is code-dead (kept one release
        # for backwards-compat introspection); if operator still has the
        # retired keys populated we emit a one-shot ERROR at setup rather
        # than silently dispatching through it.
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")

        title = "Perimeter Alert — Person Detected"
        message = PERIMETER_ENRICHMENT_BASE_TEMPLATE_PERSON.format(
            entity_id=entity_id,
            hhmmss=now.strftime("%H:%M:%S"),
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

        # PERIMETER-ALERT-NAME-PERSON-1 (Wave-1 consumer #2, 2026-09-06):
        # annotate the alert message with the recognized identity WHEN
        # KNOWN. INVARIANT: this ONLY mutates message TEXT — severity /
        # escalation are untouched. Best-effort: any failure leaves the
        # original `message` intact. Consumer of census face resolver;
        # camera_census is READ-ONLY here.
        _annotated_identity: str | None = None
        try:
            census = self.hass.data.get(DOMAIN, {}).get("census")
            _name_stem = _linker_camera or self._camera_key_for_sensor(entity_id)
            if census is not None and _name_stem and hasattr(census, "_resolve_face_legs"):
                legs = census._resolve_face_legs(_name_stem) or []
                # Highest-conf named leg. Frigate legs expose no numeric
                # confidence (conf is None) and are admitted as engine-trusted
                # (the resolver already floored them at FACE_MATCH_MIN_CONFIDENCE
                # =0.60); non-Frigate legs that DO carry a score require >=0.75.
                # So the effective floor is 0.60 for Frigate, 0.75 for scored
                # legs — display-only annotation, never affects severity.
                best_name: str | None = None
                best_conf: float = -1.0
                for leg in legs:
                    slug = getattr(leg, "canonical_slug", None)
                    if not slug:
                        continue
                    # MEDIUM-1 fix (2026-09-06 review): freshness gate. A latched
                    # face name (Protect legs auto-reset only on Frigate, not
                    # Protect) must not annotate a stale alert hours later. Drop
                    # any leg older than the latch TTL; a leg with no timestamp
                    # cannot be proven fresh and is kept lenient (display-only).
                    lc = getattr(leg, "last_changed", None)
                    if lc is not None:
                        try:
                            if (dt_util.utcnow() - lc).total_seconds() > FACE_NAME_LATCH_TTL_S:
                                continue
                        except (TypeError, ValueError):
                            pass
                    c = getattr(leg, "confidence", None)
                    if c is not None and c < 0.75:
                        continue
                    rank = c if c is not None else 0.60
                    if rank > best_conf:
                        best_conf = rank
                        best_name = slug
                if best_name:
                    _pretty = best_name.replace("_", " ").title()
                    message = f"{message} Identified: {_pretty}."
                    _annotated_identity = best_name
                    _LOGGER.info(
                        "PerimeterAlertManager: annotated %s alert with "
                        "identity=%s (conf=%s)",
                        entity_id, best_name,
                        f"{best_conf:.2f}" if best_conf >= 0 else "n/a",
                    )
        except Exception:  # noqa: BLE001 — best-effort de-escalation only
            _LOGGER.debug(
                "PerimeterAlertManager: identity annotation failed; "
                "falling back to anonymous message",
                exc_info=True,
            )

        # A-M1 short-circuit: no channels at all → don't reserve, don't
        # add in-flight, WARN and return. Post-CONSOL-1: NM is the only
        # channel — the legacy fallback is retired.
        if nm is None or not getattr(nm, "enabled", False):
            _LOGGER.warning(
                "PerimeterAlertManager: person detected on %s but NM is "
                "not configured — skipping.",
                entity_id,
            )
            # B-LOW-1: no dispatch will happen — release the seeded slot.
            self._rollback_transition_exemption(
                cooldown_key=cooldown_key, cls=exempted_class, now=now,
            )
            if held:  # PERIMETER-FP: release a D5/D10.5 hold
                self._dispatch_in_flight.discard(cooldown_key)
            return

        # --- 6b. CONSOL-1 §D3: universal llmvision enrichment.
        # Runs BETWEEN snapshot resolution and NM dispatch. Never blocks
        # or raises (INV-ENRICH-NEVER-SILENCES). Route reason distinguishes
        # success / fall-through / pre-cycle path on the ledger side.
        enriched: str | None = None
        try:
            # PERIMETER-FP D6: shadow/enforce use the verdict prompt (one
            # call). Off = the exact pre-cycle call (byte-identical).
            _vlm_mode = self._vlm_gate_mode()
            if _vlm_mode in (PERIMETER_VLM_GATE_SHADOW, PERIMETER_VLM_GATE_ENFORCE):
                enriched, _verdict = await enrich_with_verdict(
                    self.hass, snapshot_path, entity_id,
                )
                severity = self._apply_vlm_gate(
                    cooldown_key, entity_id, severity, _verdict,
                    snapshot_path, exemption_active, _vlm_mode,
                )
            else:
                enriched = await enrich_dispatched_alert(
                    self.hass, snapshot_path, entity_id,
                )
        except Exception:  # noqa: BLE001 — INV-ENRICH-NEVER-SILENCES
            _LOGGER.debug(
                "PerimeterAlertManager: enrichment adapter escaped an "
                "exception (defense-in-depth) — falling through",
                exc_info=True,
            )
            enriched = None
        if enriched:
            message = f"{message}\n\n{enriched}"
            route_reason = NM_ROUTE_REASON_ENRICHED
        else:
            # Distinguish gated-off (no adapter call) from adapter-tried-
            # and-failed by checking whether enrichment would have fired.
            try:
                _cfg = self._get_integration_config()
                _enabled = bool(_cfg.get(
                    CONF_PERIMETER_ENRICHMENT_ENABLED,
                    DEFAULT_PERIMETER_ENRICHMENT_ENABLED,
                ))
                _sensors = _cfg.get(
                    CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS
                ) or []
                if (
                    _enabled
                    and not LLMVISION_ENRICHMENT_KILL
                    and entity_id in _sensors
                    and snapshot_path
                ):
                    route_reason: str | None = (
                        NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH
                    )
                else:
                    route_reason = None
            except Exception:  # noqa: BLE001
                route_reason = None

        self._dispatch_in_flight.add(cooldown_key)

        async def _do_dispatch(_now: Any = None) -> None:
            # A-M3: don't run after teardown / during HA shutdown
            if not self._active or getattr(self.hass, "is_stopping", False):
                self._dispatch_in_flight.discard(cooldown_key)
                # B-LOW-1: teardown short-circuit — release the seed.
                self._rollback_transition_exemption(
                    cooldown_key=cooldown_key, cls=exempted_class, now=now,
                )
                return
            dispatched_ok = False
            try:
                if nm is not None and getattr(nm, "enabled", False):
                    try:
                        _kwargs: dict[str, Any] = dict(
                            coordinator_id="perimeter_alert",
                            severity=severity,
                            title=title,
                            message=message,
                            hazard_type=NM_HAZARD_EXTERIOR_PERSON,
                            location=entity_id,
                            snapshot_url=snapshot_url,
                            snapshot_path=snapshot_path,
                        )
                        if route_reason is not None:
                            _kwargs["route_reason"] = route_reason
                        await nm.async_notify(**_kwargs)
                        dispatched_ok = True
                        _LOGGER.info(
                            "PerimeterAlertManager: NM notify dispatched for "
                            "%s (severity=%s, snapshot=%s, route_reason=%s)",
                            entity_id, severity.name, bool(snapshot_url),
                            route_reason,
                        )
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.error(
                            "PerimeterAlertManager: NM notify failed for %s: %s",
                            entity_id, exc,
                        )
                    # D6 hook placeholder: future security-auto-follow can
                    # subscribe to a SIGNAL_NM_EXTERIOR_PERSON dispatch emitted
                    # here to pre-alarm the security coordinator. Not built.
                # A-M1: reserve cooldown ONLY after a successful dispatch.
                # A failed notify leaves the camera unmuted so the next
                # trigger within 5min can still alert.
                if dispatched_ok:
                    # Cycle 2: reserve cooldown by camera_key (fused-sourcing).
                    self._last_alert[cooldown_key] = now
                    # XCORR-1: record dispatched alert timestamp for the
                    # burst-count denominator. Failed dispatches never
                    # count (they don't reach this branch).
                    self._record_burst_alert(cooldown_key, now)
                    # PERIMETER-IDENTITY-FOLLOWUP-1: supersede any pending
                    # follow-up on this key; arm one if this alert went
                    # out as an unknown person at > LOW.
                    self._arm_identity_followup(
                        cooldown_key, entity_id, now, severity,
                        _annotated_identity,
                    )
                    # build/exterior-track: attribute the alert to the
                    # owning open track so future events on the same track
                    # can refine cadence (approach/circling still alert;
                    # pass_by demotes). REFINEMENT ONLY — never bypasses
                    # the per-camera cooldown gate above (INV-XP).
                    _linker = self.hass.data.get(DOMAIN, {}).get(
                        "exterior_track_linker"
                    )
                    # A-LOW-2 (2026-08-14 fix-up): mirror the cooldown-key
                    # fallback (`or entity_id`) used by the exemption gate
                    # at :1067. Without symmetry, an entity_id whose
                    # slug-strip returns None would pass the gate (via the
                    # fallback) but skip both the note_alert_dispatched
                    # AND ledger-update calls here — leaving
                    # `last_dispatched_classification` stale and letting
                    # subsequent hops re-fire the exemption unboundedly
                    # on that narrow path.
                    _cam_key = self._camera_key_for_sensor(entity_id) or entity_id
                    if _linker is not None and _cam_key:
                        try:
                            _linker.note_alert_dispatched(_cam_key, "person", now)
                        except Exception:  # noqa: BLE001
                            _LOGGER.debug(
                                "PerimeterAlertManager: linker "
                                "note_alert_dispatched failed",
                                exc_info=True,
                            )
                        # CIRCLING-LABEL-1: transition-exemption ledger
                        # update. Runs on EVERY successful dispatch (not
                        # only exemption ones) so baseline dispatches
                        # also seed `last_dispatched_classification` and
                        # the exemption gate has an accurate "last" to
                        # compare against on subsequent hops. Wire-in
                        # anchor: neutering this block collapses D3's
                        # "hop 4/5 do not re-fire" assertion (drill #4).
                        try:
                            _track = _linker.find_owning_track(
                                _cam_key, "person", now,
                            )
                            if _track is not None:
                                _cls = _linker.classify(_track)
                                _track.last_dispatched_classification = _cls
                                _track._dispatched_classifications.add(_cls)
                        except Exception:  # noqa: BLE001
                            _LOGGER.debug(
                                "PerimeterAlertManager: transition ledger "
                                "update failed",
                                exc_info=True,
                            )
            finally:
                self._dispatch_in_flight.discard(cooldown_key)
                # B-LOW-1: dispatch failed (or NM was absent inside the
                # closure) — release the optimistic exemption seed so
                # the ledger slot is available for a future legitimate
                # escalating hop. Successful dispatch already committed
                # via the ledger-update block above (idempotent add +
                # `last_dispatched_classification` set); rollback's
                # `last == cls` guard prevents double-undo.
                if not dispatched_ok:
                    self._rollback_transition_exemption(
                        cooldown_key=cooldown_key,
                        cls=exempted_class,
                        now=now,
                    )

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

    def _severity_for_current_house_state(
        self,
        camera_class: str | None = None,
        track_class: str | None = None,
    ) -> Severity:
        """Return Severity via the CONSOL-1 §6 contextual severity table.

        Fail-safe: any exception → CRITICAL. Total over 9 HouseState
        values (unknown / missing / None → CRITICAL via the case_ arm
        in NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY).
        """
        state = self._get_house_state()
        persons_home = self._get_persons_home()
        try:
            name = NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(
                state,
                camera_class=camera_class,
                track_class=track_class,
                persons_home=persons_home,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "PerimeterAlertManager: contextual severity resolver "
                "raised (%s) — coercing to CRITICAL (fail-safe).", exc,
            )
            return Severity.CRITICAL
        try:
            return Severity[name]
        except KeyError:
            _LOGGER.warning(
                "PerimeterAlertManager: unknown severity name '%s' for state "
                "'%s' — coercing to CRITICAL (fail-safe).", name, state,
            )
            return Severity.CRITICAL

    def _get_persons_home(self) -> int:
        """Return the trusted persons-home count from PresenceCoordinator.

        Fails to 0 if presence coordinator is absent — the contextual
        severity table treats `persons_home == 0` as "nobody home",
        which for home_day/home_evening yields HIGH (anomaly row 5e).
        """
        try:
            mgr = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if mgr is None:
                return 0
            presence = getattr(mgr, "presence", None) or getattr(
                mgr, "_presence_coordinator", None
            )
            if presence is None:
                return 0
            return int(
                getattr(presence, "_tracked_persons_count_trusted", 0) or 0
            )
        except Exception:  # noqa: BLE001
            return 0

    def _camera_class_for_sensor(self, sensor_entity_id: str) -> str:
        """Return 'perimeter' / 'egress' / '' by config membership."""
        try:
            cam_key = self._camera_key_for_sensor(sensor_entity_id) or ""
        except Exception:  # noqa: BLE001
            cam_key = ""
        try:
            cfg = self._get_integration_config()
        except Exception:  # noqa: BLE001
            cfg = {}
        for conf_key, label in (
            (CONF_PERIMETER_CAMERAS, "perimeter"),
            (CONF_EGRESS_CAMERAS, "egress"),
        ):
            for cam in (cfg.get(conf_key) or []):
                if cam == sensor_entity_id or (cam_key and cam.endswith(cam_key)):
                    return label
        # Fall back to "perimeter" when the sensor came off a perimeter
        # allowlist during setup — safest severity default.
        return "perimeter" if sensor_entity_id in self._perimeter_allowlist else ""

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
            # PERIMETER-FP D1 item 5: a zone sensor's Frigate camera name
            # comes from the zone map (its own stem is the ZONE name).
            _zinfo = getattr(self, "_zone_map", {}).get(sensor_entity_id)
            if _zinfo:
                cam_name = _zinfo.get("frigate_name")
            elif sensor_entity_id.startswith("binary_sensor."):
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
            # PERIMETER-FP D1 item 4: runtime zone overlay BEFORE the static
            # alias table (never mutates the const). Empty when no zones.
            _zone_key = getattr(self, "_zone_key_overrides", {}).get(slug_lc)
            if _zone_key:
                return _zone_key
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

    def _warn_if_not_leg_superset(
        self, camera_entity_id: str, base_bs: str, family: str,
        subscribed: set[str],
    ) -> set[str]:
        """TEST-1 shadow diff: WARN if the resolver leg set does not cover
        everything the retired legacy fallback would have.

        Live tripwire for silent coverage shrinkage that unit tests miss —
        the reason this card exists: a hardened surface was given new
        methods and something is bound to fall through. Observability only:
        returns the missing set and logs; NEVER changes what is subscribed.
        Returns the set of legs legacy would cover that are NOT subscribed
        (empty when the resolver set is a proper superset).
        """
        try:
            legacy_would = {
                eid for eid, _eng in self._legacy_leg_fallback(
                    base_bs, camera_entity_id, family,
                )
            }
            missing = {
                m for m in (legacy_would - subscribed)
                # PERIMETER-FP D1 item 6: deliberately excluded legs.
                if not self._is_excluded_zone_camera_leg(camera_entity_id, m, "")
            }
            if missing:
                _LOGGER.warning(
                    "PerimeterAlertManager: resolver leg set for %s is NOT a "
                    "superset of the legacy fallback — legacy would also "
                    "cover %s. Possible silent coverage shrinkage "
                    "(TEST-1 shadow diff).",
                    camera_entity_id, sorted(missing),
                )
            return missing
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PerimeterAlertManager: TEST-1 shadow diff failed for %s",
                camera_entity_id, exc_info=True,
            )
            return set()

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

    # ------------------------------------------------------------------
    # XCORR-1: burst-demotion for isolated single-camera alerts.
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # CIRCLING-LABEL-1: classification-transition exemption gate.
    # ------------------------------------------------------------------
    def _classification_transition_exemption_permitted(
        self, *, cooldown_key: str, entity_id: str, now: datetime,
    ) -> str | None:
        """Return the SEEDED target-class string when the exemption is
        permitted, or ``None`` otherwise.

        B-LOW-1 mitigation (2026-08-14 fix-up): the target class is
        added to ``track._dispatched_classifications`` BEFORE returning,
        closing a cross-camera same-track race where two concurrent
        flows on different cameras of the same track both see an empty
        set for the target class and both grant an exemption. Callers
        MUST call ``_rollback_transition_exemption(cooldown_key,
        seeded_class, now)`` on any path that ends WITHOUT a successful
        NM dispatch (S4-suppressed, NM absent, dispatch failure, handler
        exception) so a failed grant does not permanently consume the
        ledger slot for the target class.

        Semantics (see docs/planning/PLANNING_circling_label_transition_
        dispatch.md §Falsifiable invariants I1-I4):
          - I3: safeword window outranks. Return False if NM's perimeter
            silence window is active AND the hazard is not a life-safety
            hazard (matches NM's own suppress predicate at
            notification_manager.py:1468-1488).
          - I4: one exemption per (track, target_class). Return False if
            the current class is already in the track's
            `_dispatched_classifications` set.
          - I2: escalation only. Predicate is STRICT:
            `current_rank <= last_rank -> blocked` (strict `<=`, NOT `<`;
            a `<` boundary would erroneously permit re-dispatch when
            `current == last`). Unknown classes map to rank -1 so an
            unknown-vs-None comparison yields `-1 <= -1 -> blocked`
            (safe fail-closed).

        Any exception is caught by the outer try in the gate call site
        (fail-closed to False). NameError on `is_life_safety_hazard` is
        prevented by the module-level import — see Reviewer A drill #5.
        """
        # I3: safeword window outranks. Reach directly into NM's
        # RAM-only field (matches the documented private-attribute reach
        # pattern used by perimeter_diagnostics; a contract comment on
        # NM._perimeter_silence_until pins this consumer).
        try:
            nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
            if nm is not None:
                silence_until = getattr(nm, "_perimeter_silence_until", None)
                if (
                    silence_until is not None
                    and dt_util.utcnow() < silence_until
                    and not is_life_safety_hazard(
                        self.hass, NM_HAZARD_EXTERIOR_PERSON,
                    )
                ):
                    return None
        except Exception:  # noqa: BLE001
            # A-LOW-1 (2026-08-14 fix-up): promoted DEBUG -> WARNING.
            # An outer-catch hit here means the exemption stops firing
            # install-wide silently; the D3 tripwire is the only other
            # observable and it lags by ≥24h. WARNING raises ambient
            # visibility in the log without gating dispatch.
            _LOGGER.warning(
                "PerimeterAlertManager: transition-exemption safeword "
                "probe raised — fail-closed",
                exc_info=True,
            )
            return None

        # Locate the owning track. Absent linker / disabled tracking /
        # kill-switch (TRACK_LINK_WINDOW_S == 0) → no exemption.
        try:
            linker = self.hass.data.get(DOMAIN, {}).get(
                "exterior_track_linker"
            )
            if linker is None or TRACK_LINK_WINDOW_S <= 0:
                return None
            if not getattr(linker, "tracking_enabled", True):
                return None
            track = linker.find_owning_track(cooldown_key, "person", now)
            if track is None:
                return None
            current = linker.classify(track)
            last = track.last_dispatched_classification
        except Exception:  # noqa: BLE001
            # A-LOW-1 (2026-08-14 fix-up): promoted DEBUG -> WARNING
            # for the same reason as the safeword-probe catch above.
            _LOGGER.warning(
                "PerimeterAlertManager: transition-exemption linker "
                "probe raised — fail-closed",
                exc_info=True,
            )
            return None

        # I4: one exemption per (track, target_classification) pair.
        if current in track._dispatched_classifications:
            return None

        # I2: STRICT escalation. `<= -> blocked` — do NOT weaken to `<`.
        current_rank = _CLASSIFICATION_RANK.get(current, -1)
        last_rank = (
            _CLASSIFICATION_RANK.get(last, -1) if last is not None else -1
        )
        if current_rank <= last_rank:
            return None

        # B-LOW-1 (2026-08-14 fix-up): OPTIMISTIC SEED. Add the target
        # class to the ledger BEFORE returning. This closes the cross-
        # camera same-track race where two concurrent flows on
        # different cameras would both see an empty set for the target
        # class and both grant. Rollback lives in
        # `_rollback_transition_exemption`, invoked from every path
        # that ends without a successful dispatch (S4, NM-absent,
        # dispatched_ok=False).
        track._dispatched_classifications.add(current)
        return current

    def _rollback_transition_exemption(
        self, *, cooldown_key: str, cls: str | None, now: datetime,
    ) -> None:
        """Discard an optimistically-seeded exemption class.

        B-LOW-1 (2026-08-14 fix-up). Called from every path in
        ``_async_handle_perimeter_trigger`` / ``_do_dispatch`` that
        aborts BEFORE a successful NM dispatch commits the ledger via
        the ``dispatched_ok`` update block. Idempotent + fail-quiet.

        Safety guard: if ``track.last_dispatched_classification == cls``
        the ledger was already committed by a successful dispatch on
        this exact class — do NOT discard (would corrupt a successful
        grant retroactively). This can only happen if the caller
        invokes rollback in error after a successful dispatch, but
        defence-in-depth against that footgun is cheap.
        """
        if cls is None:
            return
        try:
            linker = self.hass.data.get(DOMAIN, {}).get(
                "exterior_track_linker"
            )
            if linker is None:
                return
            track = linker.find_owning_track(cooldown_key, "person", now)
            if track is None:
                return
            if track.last_dispatched_classification == cls:
                # Already committed by dispatched_ok — do not undo.
                return
            track._dispatched_classifications.discard(cls)
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PerimeterAlertManager: transition-exemption rollback "
                "raised (harmless — ledger stays as-is)",
                exc_info=True,
            )

    def _evaluate_burst_demotion(
        self, cam_key: str, entity_id: str, now: datetime,
        *, exemption_active: bool = False,
    ) -> tuple[bool, dict[str, Any]]:
        """Return (should_demote, decision_dict).

        Decision rule (all must hold to demote):
          1. Kill switch (PERIMETER_BURST_DEMOTE_ENABLED) is True.
          2. If PERIMETER_BURST_NIGHT_ONLY, we are in the alert-hours window.
          3. At least (PERIMETER_BURST_MIN_ALERTS - 1) prior dispatched
             alerts for this camera_key exist inside PERIMETER_BURST_WINDOW_S.
             (i.e. this alert would be the Nth where N >= MIN.)
          4. No sibling-engine corroboration for this camera in the
             recent-fires window (REUSED self._recent_fires — an entry
             with a different engine than the current sensor's).
          5. No adjacent-camera activity per the linker.

        The FIRST alert is sacred: condition 3 alone guarantees we never
        demote when this is the first alert in the window.

        Never silences: caller applies severity = max(severity, LOW).
        """
        decision: dict[str, Any] = {
            "camera": cam_key,
            "entity_id": entity_id,
            "at": now.isoformat(),
            "enabled": bool(PERIMETER_BURST_DEMOTE_ENABLED),
            "prior_alerts_in_window": 0,
            "sibling_corroborated": False,
            "adjacent_activity": False,
            "night_only": bool(PERIMETER_BURST_NIGHT_ONLY),
            "in_alert_hours": False,
            "demoted": False,
            "reason": "",
        }
        if not PERIMETER_BURST_DEMOTE_ENABLED:
            decision["reason"] = "disabled"
            return False, decision

        # CIRCLING-LABEL-1 D5b (HIGH-1 pin): when this dispatch was
        # permitted through the classification-transition exemption AND
        # it carries an approach/circling label, DO NOT burst-demote.
        # The exemption's whole point is that ONE dispatch labels the
        # escalating transition; demoting it defeats the founding ask
        # (a HIGH/CRITICAL circling page at the hop circling forms) on
        # every house_state × camera-shape combination — including the
        # single-camera-night shape that guards 2/3/4 all pass and
        # guard 5 (adjacent_activity) cannot block.
        if exemption_active:
            try:
                _linker = self.hass.data.get(DOMAIN, {}).get(
                    "exterior_track_linker"
                )
                _t = (
                    _linker.find_owning_track(cam_key, "person", now)
                    if _linker is not None else None
                )
                _cls = _linker.classify(_t) if _t is not None else None
            except Exception:  # noqa: BLE001
                _cls = None
            if _cls in ("approach", "circling"):
                decision["reason"] = "classification_transition_exemption"
                return False, decision

        # CONSOL-1 fix-up A4: burst-demote night_only scope uses its OWN
        # module constant (PERIMETER_BURST_NIGHT_WINDOW) — NOT any vehicle
        # or person alert-hours knob. Pre-cycle behavior preserved
        # (23-05 window). Any operator retune must be a reviewed code change.
        try:
            _start, _end = PERIMETER_BURST_NIGHT_WINDOW
            _h = now.hour
            if _start == _end:
                in_hours = True
            elif _start < _end:
                in_hours = _start <= _h < _end
            else:
                in_hours = _h >= _start or _h < _end
        except Exception:  # noqa: BLE001
            in_hours = False
        decision["in_alert_hours"] = in_hours
        if PERIMETER_BURST_NIGHT_ONLY and not in_hours:
            decision["reason"] = "outside_night_window"
            return False, decision

        # Count prior dispatched alerts for this camera inside window.
        window_s = float(PERIMETER_BURST_WINDOW_S)
        cutoff = now.timestamp() - window_s
        try:
            history = self._recent_alerts_by_camera.get(cam_key, [])
            prior = [ts for ts in history if ts.timestamp() >= cutoff]
        except Exception:  # noqa: BLE001
            prior = []
        decision["prior_alerts_in_window"] = len(prior)
        if len(prior) < max(0, PERIMETER_BURST_MIN_ALERTS - 1):
            decision["reason"] = "first_alert"
            return False, decision

        # Sibling-engine corroboration on THIS camera: consult _recent_fires
        # (bounded to _SOLE_FIRE_WINDOW_S) — if any entry from an engine
        # different than the current sensor's is present, we treat this
        # camera as corroborated and DO NOT demote.
        current_engine = self._sensor_engine.get(entity_id) or ""
        sibling = False
        try:
            fires_cutoff = now.timestamp() - float(self._SOLE_FIRE_WINDOW_S)
            recent = self._recent_fires.get(cam_key, [])
            for (eng, ts) in recent:
                if ts.timestamp() < fires_cutoff:
                    continue
                # PERIMETER-FP D1 item 8 (§0.6.4): compare NVR FAMILIES, not
                # engine strings, so a zone leg (frigate) and a leftover
                # camera leg (frigate2) never "corroborate" each other.
                if eng and nvr_family(eng) != nvr_family(current_engine):
                    sibling = True
                    break
        except Exception:  # noqa: BLE001
            sibling = False
        decision["sibling_corroborated"] = sibling
        if sibling:
            decision["reason"] = "sibling_corroborated"
            return False, decision

        # Adjacent-camera activity via linker.
        adj = False
        try:
            linker = self.hass.data.get(DOMAIN, {}).get(
                "exterior_track_linker"
            )
            if linker is not None and hasattr(
                linker, "has_recent_adjacent_activity"
            ):
                adj = bool(linker.has_recent_adjacent_activity(
                    cam_key, window_s, now,
                ))
        except Exception:  # noqa: BLE001
            adj = False
        decision["adjacent_activity"] = adj
        if adj:
            decision["reason"] = "adjacent_activity"
            return False, decision

        decision["demoted"] = True
        decision["reason"] = "burst_isolated"
        return True, decision

    def _record_suppression(
        self, cam_key: str, reason: str, **detail: Any
    ) -> None:
        """Record WHY an alert was suppressed before dispatch.

        CIRCLING-SEVERITY-1. Observability only — never changes control
        flow. Mirrors the burst path's ``decision["reason"]`` idiom rather
        than introducing a second vocabulary.
        """
        try:
            self._last_suppression[cam_key] = {
                "reason": reason,
                "at": dt_util.now().isoformat(),
                **detail,
            }
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PerimeterAlertManager: _record_suppression failed",
                exc_info=True,
            )

    def _record_burst_alert(self, cam_key: str, now: datetime) -> None:
        """Append a dispatched-alert timestamp and prune stale entries.

        Called from the dispatch path AFTER dispatched_ok so failed alerts
        do not count toward the burst-count denominator (same principle as
        the cooldown reservation).
        """
        try:
            history = self._recent_alerts_by_camera.setdefault(cam_key, [])
            cutoff = now.timestamp() - float(PERIMETER_BURST_WINDOW_S)
            history = [ts for ts in history if ts.timestamp() >= cutoff]
            history.append(now)
            # Bounded — the cooldown floor guarantees << 64 entries per
            # window in practice; guard against pathological config.
            self._recent_alerts_by_camera[cam_key] = history[-64:]
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "PerimeterAlertManager: _record_burst_alert failed",
                exc_info=True,
            )

    def burst_demotion_stats(self) -> dict[str, dict[str, Any]]:
        """Return per-camera burst-demotion decisions + counts.

        Consumed by the exterior open-tracks diagnostic sensor
        (`attrs["burst_demotions_by_camera"]`) so the operator can see WHY
        an alert was demoted (or not) without log-level surgery.

        Shape (dashboard-friendly):
          {
            "<camera_key>": {
              "last_decision": {...decision_dict...},
              "alerts_in_window": int,
              "window_s": int,
            }, ...
          }
        """
        now = dt_util.now()
        cutoff = now.timestamp() - float(PERIMETER_BURST_WINDOW_S)
        out: dict[str, dict[str, Any]] = {}
        cams = set(self._last_burst_decision) | set(
            self._recent_alerts_by_camera
        )
        for cam in cams:
            last = self._last_burst_decision.get(cam)
            history = self._recent_alerts_by_camera.get(cam, [])
            count = sum(1 for ts in history if ts.timestamp() >= cutoff)
            out[cam] = {
                "last_decision": last,
                "alerts_in_window": count,
                "window_s": int(PERIMETER_BURST_WINDOW_S),
            }
        return out

    def suppression_stats(self) -> dict[str, dict[str, Any]]:
        """Return the most recent PRE-DISPATCH suppression per camera.

        CIRCLING-SEVERITY-1. Consumed by the exterior open-tracks
        diagnostic sensor as ``attrs["suppressions_by_camera"]`` so the
        operator can tell WHICH gate stopped an alert without raising log
        levels and waiting for a recurrence (the soak-watch the card's
        original plan proposed, which doctrine forbids).

        Reasons: ``egress_suppression`` | ``cooldown``.
        """
        return dict(self._last_suppression)

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
            # PERIMETER-FP D5: forward-scan hook for open agreement samples.
            if hasattr(self, "_agreement"):
                self._agreement_note_fire(cam_key, engine, now)
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
                    # PERIMETER-FP D1 (rev 2, H3): the zone exclusion also
                    # holds post-HA_STARTED, or the dropped leg returns.
                    if self._is_excluded_zone_camera_leg(
                        cam_entity_id, leg.entity_id, leg.engine,
                    ):
                        continue
                    self._sensor_to_camera[leg.entity_id] = cam_entity_id
                    self._sensor_platforms[leg.entity_id] = leg.integration or ""
                    self._sensor_engine[leg.entity_id] = leg.engine
                    # Review A-L1 / B-LOW-1: late legs feed liveness too.
                    _ck = self._camera_key_for_sensor(leg.entity_id) or leg.entity_id
                    self._person_legs_by_key.setdefault(_ck, set()).add(leg.entity_id)
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

    def _is_in_vehicle_alert_hours(self, now: datetime) -> bool:
        """True when `now` is inside the deep-night vehicle-alert window.

        CONSOL-1 §D6 — reads the RENAMED, operator-tunable keys
        (CONF_PERIMETER_VEHICLE_HOURS_START/_END). The old
        module-constant fallbacks (EXTERIOR_VEHICLE_NIGHT_START/_END)
        remain the DEFAULTS if the operator hasn't configured a
        window (defaults 22 / 6 → 10pm-6am, WIDER than the person-
        path's retired 23-05 window on purpose: vehicles are a
        deep-night signal).

        Window semantics: start < end is same-day, start >= end wraps
        at midnight.
        """
        try:
            cfg = self._get_integration_config()
        except Exception:  # noqa: BLE001
            cfg = {}
        start = cfg.get(
            CONF_PERIMETER_VEHICLE_HOURS_START,
            EXTERIOR_VEHICLE_NIGHT_START,
        )
        end = cfg.get(
            CONF_PERIMETER_VEHICLE_HOURS_END,
            EXTERIOR_VEHICLE_NIGHT_END,
        )
        try:
            start = int(start)
            end = int(end)
        except (TypeError, ValueError):
            start = EXTERIOR_VEHICLE_NIGHT_START
            end = EXTERIOR_VEHICLE_NIGHT_END
        h = now.hour
        if start == end:
            return True
        if start < end:
            return start <= h < end
        return h >= start or h < end

    # Back-compat alias for pre-CONSOL-1 callers (deprecated, one release).
    def _in_vehicle_night_window(self, now: datetime) -> bool:
        return self._is_in_vehicle_alert_hours(now)

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

        if not self._is_in_vehicle_alert_hours(now):
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
        # SNAP-1 fix-up (F6+F7): thread the at-detection LOCAL FILE
        # through the vehicle path exactly as the person path does.
        # Kill-switch check is centralized in the capture helper — no
        # duplicate guard here.
        snapshot_path = await self._await_edge_capture(sensor_entity_id)
        if snapshot_path:
            delay_s = 0

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
        if nm is None or not getattr(nm, "enabled", False):
            _LOGGER.warning(
                "PerimeterAlertManager: vehicle on %s but NM not "
                "configured — skipping.", sensor_entity_id,
            )
            return

        # --- CONSOL-1 §D3: enrichment on the vehicle leg (S2).
        veh_enriched: str | None = None
        try:
            veh_enriched = await enrich_dispatched_alert(
                self.hass, snapshot_path, sensor_entity_id,
            )
        except Exception:  # noqa: BLE001 — INV-ENRICH-NEVER-SILENCES
            veh_enriched = None
        if veh_enriched:
            message = f"{message}\n\n{veh_enriched}"
            veh_route_reason: str | None = NM_ROUTE_REASON_ENRICHED
        else:
            try:
                _cfg = self._get_integration_config()
                _en = bool(_cfg.get(
                    CONF_PERIMETER_ENRICHMENT_ENABLED,
                    DEFAULT_PERIMETER_ENRICHMENT_ENABLED,
                ))
                _sensors = _cfg.get(
                    CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS
                ) or []
                if (
                    _en
                    and not LLMVISION_ENRICHMENT_KILL
                    and sensor_entity_id in _sensors
                    and snapshot_path
                ):
                    veh_route_reason = (
                        NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH
                    )
                else:
                    veh_route_reason = None
            except Exception:  # noqa: BLE001
                veh_route_reason = None

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
                        _kwargs: dict[str, Any] = dict(
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
                            snapshot_path=snapshot_path,
                        )
                        if veh_route_reason is not None:
                            _kwargs["route_reason"] = veh_route_reason
                        await nm.async_notify(**_kwargs)
                        dispatched_ok = True
                        _LOGGER.info(
                            "PerimeterAlertManager: vehicle NM dispatched "
                            "for %s (severity=%s, class=%s, state=%s, "
                            "route_reason=%s)",
                            cooldown_key, severity.name, classification,
                            house_state, veh_route_reason,
                        )
                    except Exception as exc:  # noqa: BLE001
                        _LOGGER.error(
                            "PerimeterAlertManager: vehicle NM failed for "
                            "%s: %s", cooldown_key, exc,
                        )
                # CONSOL-1 §D1: legacy fallback RETIRED on the vehicle
                # leg as well. See `_async_send_legacy_notification`
                # (code-dead, one release only).
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

            # SNAP-1 fix-up (F3): resolve symlinks BOTH sides AFTER
            # makedirs so the created leaf is real. os.path.abspath only
            # normalizes '..' — it does NOT follow symlinks, so a
            # snapshot dir that (or whose parent) symlinks into www
            # would pass the old guard. realpath() closes that hole.
            if www_path:
                try:
                    www_real = os.path.realpath(www_path)
                    dir_real = os.path.realpath(dir_path)
                except Exception:  # noqa: BLE001
                    www_real = None
                    dir_real = None
                if www_real and dir_real and (
                    dir_real == www_real
                    or dir_real.startswith(www_real + os.sep)
                ):
                    self._snapshot_kill_legacy_url = True
                    _LOGGER.error(
                        "SNAP-1: snapshot dir %s (real=%s) is under HA www "
                        "path %s (real=%s) — refusing to write (web-served "
                        "privacy invariant). Engaging legacy URL fallback.",
                        dir_path, dir_real, www_path, www_real,
                    )
                    return

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

    # ------------------------------------------------------------------
    # SNAP-1 fix-up (F1): at-detection edge-capture
    # ------------------------------------------------------------------

    def _maybe_start_edge_capture(self, sensor_entity_id: str) -> None:
        """Kick off at-detection capture at the sensor RISING EDGE.

        Called from `_on_perimeter_event` and `_on_vehicle_state_change`
        BEFORE the handler task is scheduled — this is the site the
        cycle's stated invariant depends on ("a shot from when it
        happened/fired, not seconds later when code runs for
        alerting"). Dedup by collapsed camera_key so a second engine
        leg firing the same physical event does NOT start a second
        capture. Bounded buffer (LRU-ish: evict oldest when over cap).
        """
        try:
            if self._snapshot_kill_legacy_url:
                return
            if not sensor_entity_id:
                return
            cam_key = (
                self._camera_key_for_sensor(sensor_entity_id)
                or sensor_entity_id
            )
            now_mono = _time.monotonic()
            existing = self._edge_captures.get(cam_key)
            if existing is not None:
                age = now_mono - float(existing.get("started_ts") or 0.0)
                if age < PERIMETER_SNAPSHOT_EDGE_DEDUP_S:
                    return
                # Stale entry — drop and start fresh.
                self._edge_captures.pop(cam_key, None)
                try:
                    task = existing.get("task")
                    if task is not None and not task.done():
                        task.cancel()
                except Exception:  # noqa: BLE001
                    pass
            # LRU-ish bound: if at cap, drop the OLDEST entry (and
            # cancel its task) so buffer size cannot grow without
            # limit even if capture consistently outpaces handler
            # consumption (e.g. under a stall).
            if (
                len(self._edge_captures)
                >= PERIMETER_SNAPSHOT_EDGE_CAPTURES_MAX
            ):
                try:
                    oldest_key = min(
                        self._edge_captures,
                        key=lambda k: float(
                            self._edge_captures[k].get("started_ts") or 0.0
                        ),
                    )
                    dropped = self._edge_captures.pop(oldest_key, None)
                    if dropped is not None:
                        t = dropped.get("task")
                        if t is not None and not t.done():
                            t.cancel()
                except Exception:  # noqa: BLE001
                    pass
            task = self.hass.async_create_task(
                self._capture_at_detection_snapshot(sensor_entity_id)
            )
            self._edge_captures[cam_key] = {
                "task": task,
                "started_ts": now_mono,
                "started_at": dt_util.now(),
                "entity_id": sensor_entity_id,
            }
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "SNAP-1: edge-capture start failed for %s",
                sensor_entity_id, exc_info=True,
            )

    async def _await_edge_capture(
        self, sensor_entity_id: str,
    ) -> str | None:
        """Consume the edge-initiated capture for this sensor's camera.

        Handler consumes the buffered result and records the
        edge->consumption delta into the capture ledger so the
        "at-detection" property is MEASURABLE. If no edge entry
        exists (e.g. tests calling the handler directly, or an entry
        was already consumed by a sibling engine leg), fall back to
        an inline capture inside the same budget.
        """
        cam_key = (
            self._camera_key_for_sensor(sensor_entity_id)
            or sensor_entity_id
        )
        entry = self._edge_captures.pop(cam_key, None)
        if entry is None:
            # Fallback path — inline capture (also budget-bounded).
            return await self._capture_at_detection_snapshot(
                sensor_entity_id
            )
        task = entry.get("task")
        started_ts = float(entry.get("started_ts") or 0.0)
        # Drop stale entries silently — file (if any) will be reaped
        # by the periodic prune sweep.
        if (
            started_ts
            and (_time.monotonic() - started_ts)
            > PERIMETER_SNAPSHOT_EDGE_TTL_S
        ):
            try:
                if task is not None and not task.done():
                    task.cancel()
            except Exception:  # noqa: BLE001
                pass
            return None
        budget = max(0.1, float(PERIMETER_SNAPSHOT_CAPTURE_BUDGET_S))
        try:
            path = await asyncio.wait_for(task, timeout=budget)
        except asyncio.TimeoutError:
            _LOGGER.debug(
                "SNAP-1: edge-capture await budget (%.1fs) exceeded "
                "for %s — dispatch proceeds without image.",
                budget, sensor_entity_id,
            )
            return None
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "SNAP-1: edge-capture task raised for %s",
                sensor_entity_id, exc_info=True,
            )
            return None
        # Record edge->consumption delta (F1 measurability requirement).
        try:
            delta_ms = int(
                (_time.monotonic() - started_ts) * 1000
            )
            entry_ref = self._last_snapshot_capture.get(
                cam_key or "camera"
            )
            if isinstance(entry_ref, dict):
                entry_ref["edge_started_at"] = (
                    entry.get("started_at").isoformat()
                    if entry.get("started_at") is not None
                    else None
                )
                entry_ref["edge_to_consume_ms"] = delta_ms
        except Exception:  # noqa: BLE001
            pass
        return path

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

        # SNAP-1 fix-up (F5): whole-capture budget. A stalled camera
        # or wedged Frigate must NOT delay the security page more
        # than PERIMETER_SNAPSHOT_CAPTURE_BUDGET_S seconds; on
        # timeout, dispatch proceeds without an image (URL fallback
        # remains).
        try:
            if PERIMETER_SNAPSHOT_CAPTURE_BUDGET_S > 0:
                return await asyncio.wait_for(
                    self._capture_precedence(
                        cam_key, camera_entity_id, platform, now_ts,
                    ),
                    timeout=PERIMETER_SNAPSHOT_CAPTURE_BUDGET_S,
                )
            return await self._capture_precedence(
                cam_key, camera_entity_id, platform, now_ts,
            )
        except asyncio.TimeoutError:
            _LOGGER.debug(
                "SNAP-1: capture budget (%ds) exceeded for %s — "
                "dispatch proceeds without image.",
                PERIMETER_SNAPSHOT_CAPTURE_BUDGET_S, sensor_entity_id,
            )
            return None

    async def _capture_precedence(
        self, cam_key: str, camera_entity_id: str,
        platform: str, now_ts: int,
    ) -> str | None:
        """Iterate PERIMETER_SNAPSHOT_ENGINE_PRECEDENCE in order.

        SNAP-1 fix-up (F8): REAL precedence — dispatch by name in the
        order the tuple lists them (was fixed source order with
        membership checks; reordering the tuple had zero runtime
        effect). Unknown engine names are skipped with a DEBUG log.
        """
        for engine in PERIMETER_SNAPSHOT_ENGINE_PRECEDENCE:
            if engine == "frigate_event":
                path = await self._try_capture_frigate_event(
                    cam_key, camera_entity_id, platform, now_ts,
                )
                if path:
                    return path
            elif engine == "protect_thumb":
                # Verified NOT VIABLE at the detection edge — see
                # docstring on _capture_at_detection_snapshot.
                continue
            elif engine == "live_grab":
                path = await self._try_capture_live_grab(
                    cam_key, camera_entity_id, now_ts,
                )
                if path:
                    return path
            else:
                _LOGGER.debug(
                    "SNAP-1: unknown engine '%s' in precedence — skipped.",
                    engine,
                )
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
        # v5.107.2 Fix C: an id whose event already ENDED belongs to a
        # previous track — never fetch its frame for this edge (second
        # walk-past would show the first person). Fall to live_grab.
        if getattr(self, "_frigate_ended_event_id", {}).get(
            (cam_key or "").strip().lower()
        ) == eid:
            return None
        # SNAP-1 fix-up (F2): sanitize the event id before it is ever
        # interpolated into a filesystem path OR a URL. os.path.join
        # does NOT neutralize '..'; a malicious `frigate_events`
        # publisher could write outside PERIMETER_SNAPSHOT_DIR without
        # this guard. Sanitize cam_key too (same interpolation risk).
        eid_safe = _sanitize_snapshot_token(eid)
        cam_safe = _sanitize_snapshot_token(cam_key) or "camera"
        if not eid_safe:
            _LOGGER.debug(
                "SNAP-1: refusing Frigate capture — event id sanitizer "
                "rejected %r (cam_key=%r)", eid, cam_key,
            )
            return None

        # SNAP-1 fix-up (F4): when Frigate is multi-instance, do NOT
        # try the default (non-instance-scoped) URL first. With
        # `armcrest*` on both hosts + known cross-host MQTT topic
        # collision, the default URL can silently return ANOTHER
        # camera's image. Wrong image is worse than no image.
        candidates: list[str] = []
        learned = self._camera_frigate_instance.get(cam_key)
        if learned:
            candidates.append(
                f"/api/frigate/{learned}/notifications/{eid_safe}/snapshot.jpg"
            )
        for inst in self._frigate_instance_ids:
            u = f"/api/frigate/{inst}/notifications/{eid_safe}/snapshot.jpg"
            if u not in candidates:
                candidates.append(u)
        if not self._frigate_instance_ids:
            # Single-instance (or Frigate integration absent) — default
            # URL shape is safe.
            candidates.append(
                f"/api/frigate/notifications/{eid_safe}/snapshot.jpg"
            )

        for url_path in candidates:
            data = await self._http_get_bytes(url_path)
            if not data:
                # SNAP-1 fix-up (F4): invalidate learned instance on
                # miss — a camera migrating between hosts must not
                # keep hitting the wrong Frigate.
                if learned and url_path.startswith(
                    f"/api/frigate/{learned}/"
                ):
                    self._camera_frigate_instance.pop(cam_key, None)
                continue
            # Learn instance if the successful URL was instance-scoped.
            if url_path.startswith("/api/frigate/") and "notifications" in url_path:
                parts = url_path.split("/")
                if len(parts) >= 4 and parts[3] != "notifications":
                    self._camera_frigate_instance[cam_key] = parts[3]
            file_path = os.path.join(
                PERIMETER_SNAPSHOT_DIR,
                f"{cam_safe}_{eid_safe}.jpg",
            )
            if not _path_within(file_path, PERIMETER_SNAPSHOT_DIR):
                _LOGGER.error(
                    "SNAP-1: refusing frigate write — target %s escapes "
                    "%s", file_path, PERIMETER_SNAPSHOT_DIR,
                )
                return None
            if await self._write_snapshot_file(
                file_path, data, "frigate_event", cam_safe,
            ):
                return file_path
        return None

    async def _try_capture_live_grab(
        self, cam_key: str, camera_entity_id: str, now_ts: int,
    ) -> str | None:
        """Call `camera.snapshot` service on the mapped camera."""
        if not camera_entity_id:
            return None
        # SNAP-1 fix-up (F2): sanitize cam_key. SNAP-1 fix-up (F9e):
        # append short random suffix so two captures in the same second
        # do not collide.
        cam_safe = _sanitize_snapshot_token(cam_key) or "camera"
        rnd = os.urandom(3).hex()
        file_path = os.path.join(
            PERIMETER_SNAPSHOT_DIR,
            f"{cam_safe}_{now_ts}_{rnd}.jpg",
        )
        # SNAP-1 fix-up (F2 + F3): containment check before we ask HA
        # to write.
        if not _path_within(file_path, PERIMETER_SNAPSHOT_DIR):
            _LOGGER.error(
                "SNAP-1: refusing live-grab write — target %s escapes %s",
                file_path, PERIMETER_SNAPSHOT_DIR,
            )
            return None
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
        self._note_capture(cam_safe, file_path, "live_grab", size)
        await self._async_prune_snapshot_dir()
        return file_path

    @staticmethod
    def _stat_size(path: str) -> int:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def _internal_base_url(self) -> str | None:
        """Internal-only base URL for SERVER-SIDE fetches (v5.107.2).

        PERIMETER-FRIGATE-SNAPSHOT-CAPTURE-NEVER-1: `_absolutize` prefers
        `external_url`, which (Cloudflare-fronted) times out from the HA
        host, so the 2 s SNAP-1 tier-1 fetch never succeeded. A fetch
        made BY this process must use an internal base. Uses HA's
        `network.get_url` with external + cloud disallowed (it falls back
        through internal_url to the local api ip:port). Never returns an
        external URL; None when no internal URL is available.
        `_absolutize` stays the builder for OUTBOUND links (Pushover /
        WhatsApp `snapshot_url`), which need the public host.
        """
        try:
            from homeassistant.helpers.network import get_url  # noqa: PLC0415
            base = get_url(
                self.hass,
                allow_external=False,
                allow_cloud=False,
                prefer_external=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("SNAP-1: no internal URL available", exc_info=True)
            return None
        if not isinstance(base, str) or "://" not in base:
            return None
        return base.rstrip("/")

    async def _http_get_bytes(self, url_path: str) -> bytes | None:
        """HTTP GET a relative HA URL, return bytes or None on failure.

        Server-side fetch: resolves against the INTERNAL base, never the
        external one (see `_internal_base_url`).
        """
        if not url_path:
            return None
        if "://" in url_path:
            # Relative paths only: an absolute URL could send the fetch outward.
            return None
        base = self._internal_base_url()
        if not base:
            return None
        abs_url = base + url_path
        try:
            from homeassistant.helpers.aiohttp_client import (
                async_get_clientsession,
            )
            session = async_get_clientsession(self.hass)
            # SNAP-1 fix-up (F5): explicit ClientTimeout (aiohttp
            # default 300s would let a wedged Frigate stall well past
            # the whole-capture budget). Import lazily so the test
            # stub prelude does not have to provide aiohttp.
            try:
                import aiohttp  # noqa: PLC0415
                timeout = aiohttp.ClientTimeout(
                    total=max(1, PERIMETER_SNAPSHOT_HTTP_TIMEOUT_S)
                )
                async with session.get(abs_url, timeout=timeout) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.read()
            except ImportError:
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
        cam_key: str | None = None,
    ) -> bool:
        """Write bytes to file in executor; record + prune on success.

        SNAP-1 fix-up (F9a): callers now pass `cam_key` explicitly. The
        previous derivation `basename.split('_')[0]` corrupted names
        with an underscore stem (`rear_ptz` → `rear`) and collided two
        cameras sharing a first segment in the ledger.
        SNAP-1 fix-up (F3 defence-in-depth): re-check containment
        before writing.
        """
        if not data:
            return False
        if not _path_within(file_path, PERIMETER_SNAPSHOT_DIR):
            _LOGGER.error(
                "SNAP-1: refusing write — %s escapes %s",
                file_path, PERIMETER_SNAPSHOT_DIR,
            )
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
        if cam_key is None:
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

    async def _async_prune_snapshot_dir(self, force: bool = False) -> None:
        """Prune snapshot dir by age (primary) + count (backstop).

        SNAP-1 fix-up (F9b): on-write prune is debounced —
        PERIMETER_SNAPSHOT_PRUNE_DEBOUNCE_S seconds between per-write
        runs. `force=True` bypasses the debounce (used by the periodic
        sweep tick).
        """
        try:
            now = _time.time()
            if not force:
                if (
                    self._last_prune_ts
                    and (now - self._last_prune_ts)
                    < PERIMETER_SNAPSHOT_PRUNE_DEBOUNCE_S
                ):
                    return
            self._last_prune_ts = now
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
        self.hass.async_create_task(
            self._async_prune_snapshot_dir(force=True)
        )

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
        # PERIMETER-FP D2: Frigate-leg edge counter (bus-silent trip-wire).
        self._note_frigate_leg_edge(entity_id)
        # SNAP-1 fix-up (F1): kick off at-detection capture NOW, at the
        # sensor rising edge — before alert-hours / egress / cooldown /
        # in-flight / severity / linker checks. The handler consumes
        # the buffered result inside its own budget. One-file-per-
        # collapsed-camera-key dedup is enforced by keying the buffer
        # by cam_key (a second engine leg fires the same physical
        # event and finds the buffer entry).
        self._maybe_start_edge_capture(entity_id)
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
    # PERIMETER-FP-STREET-NOISE-1 (v5.107.0) — gates D1-D6, D10
    # PLANNING_perimeter_fp_build_2026_11.md. Every gate DEMOTES ONLY
    # (floor LOW) and fails open on missing / stale / malformed input.
    # ------------------------------------------------------------------

    _FRIGATE_EVENT_FIELDS: tuple[str, ...] = (
        "id", "score", "top_score", "box", "current_zones",
        "entered_zones", "stationary",
    )

    @staticmethod
    def _camera_slug_stem(camera_entity_id: str) -> str:
        """camera.<slug>[channel suffix] -> lowercase slug stem."""
        if not camera_entity_id or not camera_entity_id.startswith("camera."):
            return ""
        slug = camera_entity_id[len("camera."):]
        for suf in CAMERA_RESOLUTION_CHANNEL_SUFFIXES:
            if slug.endswith(suf):
                slug = slug[: -len(suf)]
                break
        return slug.lower()

    def _build_zone_map(self, perimeter_infos: list) -> None:
        """D1 item 2: map each configured zone sensor to ONE perimeter camera.

        Rungs: (a) the zone stem starts with `<camera stem>_` for exactly one
        camera (longest stem wins; a tie between cameras = no match);
        (b) EXTERIOR_CAMERA_KEY_ALIASES entry for the zone stem naming a
        configured camera's key. No match: WARN, the sensor is not
        subscribed and the camera keeps today's legs. The Frigate private
        config read (rev-1 rung) is PARKED (load-order nondeterminism).
        """
        self._zone_map = {}
        self._zoned_cameras = {}
        self._zone_key_overrides = {}
        try:
            zones = list(
                self._get_integration_config().get(CONF_PERIMETER_ZONE_SENSORS) or []
            )
        except Exception:  # noqa: BLE001
            zones = []
        if not zones:
            return
        # camera entity -> candidate (unaliased, lowercase) stems.
        cand: dict[str, set[str]] = {}
        for cam_entity_id, info in perimeter_infos:
            stems = cand.setdefault(cam_entity_id, set())
            base_bs = getattr(info, "person_binary_sensor", "") or ""
            if base_bs.startswith("binary_sensor."):
                st, _m = self._strip_person_family_suffixes(
                    base_bs[len("binary_sensor."):]
                )
                if st:
                    stems.add(st.lower())
            cs = self._camera_slug_stem(cam_entity_id)
            if cs:
                stems.add(cs)
        for zone in zones:
            if not isinstance(zone, str) or not zone.startswith("binary_sensor."):
                continue
            zstem, _m = self._strip_person_family_suffixes(
                zone[len("binary_sensor."):]
            )
            if not zstem:
                _LOGGER.warning(
                    "PerimeterAlertManager: zone sensor %s is not a person "
                    "sensor — ignored", zone,
                )
                continue
            zstem = zstem.lower()
            best_len = -1
            best: list[tuple[str, str]] = []  # (camera, stem)
            for cam_entity_id, stems in cand.items():
                for st in stems:
                    if zstem.startswith(f"{st}_"):
                        if len(st) > best_len:
                            best_len, best = len(st), [(cam_entity_id, st)]
                        elif len(st) == best_len:
                            best.append((cam_entity_id, st))
            match: tuple[str, str] | None = None
            if best and len({c for c, _s in best}) == 1:
                match = best[0]
            if match is None:
                alias = _EXTERIOR_CAMERA_KEY_ALIASES_LC.get(zstem)
                if alias:
                    hits = [
                        (c, st) for c, stems in cand.items() for st in stems
                        if _EXTERIOR_CAMERA_KEY_ALIASES_LC.get(st, st) == alias
                    ]
                    if hits and len({c for c, _s in hits}) == 1:
                        match = hits[0]
            if match is None:
                _LOGGER.warning(
                    "PerimeterAlertManager: zone sensor %s maps to no unique "
                    "perimeter camera — not subscribed; camera legs unchanged",
                    zone,
                )
                continue
            cam_entity_id, stem = match
            cam_key = _EXTERIOR_CAMERA_KEY_ALIASES_LC.get(stem, stem)
            self._zone_map[zone] = {
                "camera": cam_entity_id,
                "camera_key": cam_key,
                "frigate_name": stem,
                "zone_slug": zone_slug(zstem),
            }
            self._zoned_cameras.setdefault(cam_entity_id, []).append(zone)
            self._zone_key_overrides[zstem] = cam_key

    @staticmethod
    def _is_frigate_person_entity(entity_id: str) -> bool:
        return entity_id.endswith("_person_occupancy") or entity_id.endswith(
            "_person_occupancy_2"
        )

    def _is_excluded_zone_camera_leg(
        self, cam_entity_id: str, entity_id: str, engine: str,
    ) -> bool:
        """D1: True for a camera-level Frigate person leg of a zoned camera."""
        zones = getattr(self, "_zoned_cameras", {}).get(cam_entity_id)
        if not zones or entity_id in zones:
            return False
        return nvr_family(engine) == "frigate" or self._is_frigate_person_entity(
            entity_id
        )

    # ---- D2 -----------------------------------------------------------
    def _note_frigate_event(
        self, cam_name: str, msg_type: str, after: dict,
    ) -> None:
        try:
            now = dt_util.now()
            rec = {k: after.get(k) for k in self._FRIGATE_EVENT_FIELDS}
            rec["type"] = msg_type or None
            rec["received_at"] = now
            self._frigate_event_cache[cam_name] = rec
            self._append_window(self._frigate_bus_times, cam_name, now.timestamp())
        except Exception:  # noqa: BLE001
            _LOGGER.debug("PerimeterAlertManager: D2 cache failed", exc_info=True)

    @staticmethod
    def _append_window(store: dict[str, list[float]], key: str, ts: float) -> None:
        cutoff = ts - float(PERIMETER_FRIGATE_BUS_WINDOW_S)
        lst = [t for t in store.get(key, []) if t >= cutoff]
        lst.append(ts)
        store[key] = lst[-5000:]

    def _frigate_name_for_sensor(self, entity_id: str) -> str:
        z = self._zone_map.get(entity_id)
        if z:
            return z.get("frigate_name") or ""
        if not entity_id.startswith("binary_sensor."):
            return ""
        st, _m = self._strip_person_family_suffixes(entity_id[len("binary_sensor."):])
        return (st or "").lower()

    def _note_frigate_leg_edge(self, entity_id: str) -> None:
        """D2: count Frigate-family person-leg rising edges; bus-silent WARN."""
        try:
            if nvr_family(self._sensor_engine.get(entity_id)) != "frigate":
                return
            name = self._frigate_name_for_sensor(entity_id)
            if not name:
                return
            now_ts = dt_util.now().timestamp()
            self._append_window(self._frigate_edge_times, name, now_ts)
            if (
                PERIMETER_FRIGATE_BUS_SILENT_MIN_EDGES > 0
                and not self._frigate_bus_silent_warned
            ):
                cutoff = now_ts - float(PERIMETER_FRIGATE_BUS_WINDOW_S)
                edges = sum(
                    1 for v in self._frigate_edge_times.values() for t in v if t >= cutoff
                )
                bus = sum(
                    1 for v in self._frigate_bus_times.values() for t in v if t >= cutoff
                )
                if edges >= PERIMETER_FRIGATE_BUS_SILENT_MIN_EDGES and bus == 0:
                    self._frigate_bus_silent_warned = True
                    _LOGGER.warning(
                        "PerimeterAlertManager: Frigate person legs rose %d "
                        "times in %ds with ZERO frigate_events bus messages — "
                        "the MQTT-to-frigate_events bridge automation looks "
                        "broken (D9 revival trigger).",
                        edges, int(PERIMETER_FRIGATE_BUS_WINDOW_S),
                    )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("PerimeterAlertManager: D2 edge count failed", exc_info=True)

    def frigate_bus_stats(self) -> dict[str, dict[str, Any]]:
        """D2 diagnostic (display only)."""
        cutoff = dt_util.now().timestamp() - float(PERIMETER_FRIGATE_BUS_WINDOW_S)
        out: dict[str, dict[str, Any]] = {}
        for name in set(self._frigate_bus_times) | set(self._frigate_edge_times) | set(
            self._frigate_event_cache
        ):
            rec = dict(self._frigate_event_cache.get(name) or {})
            if isinstance(rec.get("received_at"), datetime):
                rec["received_at"] = rec["received_at"].isoformat()
            out[name] = {
                "frigate_events_24h": sum(
                    1 for t in self._frigate_bus_times.get(name, []) if t >= cutoff
                ),
                "frigate_leg_edges_24h": sum(
                    1 for t in self._frigate_edge_times.get(name, []) if t >= cutoff
                ),
                "last_event": rec or None,
            }
        return out

    # ---- shared -------------------------------------------------------
    def _options_flag(self, key: str, default: Any) -> Any:
        """Fresh-read an integration option (switch / select backed)."""
        try:
            return self._get_integration_config().get(key, default)
        except Exception:  # noqa: BLE001
            return default

    def _record_gate(self, cam_key: str, decision: dict[str, Any]) -> None:
        try:
            self._last_gate_decisions.setdefault(cam_key, {})[
                decision.get("gate", "?")
            ] = decision
        except Exception:  # noqa: BLE001
            pass

    def gate_decision_stats(self) -> dict[str, Any]:
        """Diagnostic sensor surface: last decision per gate per camera,
        D5 agreement table, D2 bus counters. Display only."""
        return {
            "gate_decisions_by_camera": dict(self._last_gate_decisions),
            "agreement_by_camera": self._agreement.stats(),
            "agreement_store_loaded": self._agreement_load_ok,
            "frigate_bus_by_camera": self.frigate_bus_stats(),
            "zone_map": {k: dict(v) for k, v in self._zone_map.items()},
            "dual_role_cameras": sorted(self._dual_role_cameras),
        }

    def _exemption_shields(
        self, cam_key: str, now: datetime, exemption_active: bool,
    ) -> bool:
        """INV-FP-EXEMPTION: same predicate as the burst gate."""
        if not exemption_active:
            return False
        try:
            lk = self.hass.data.get(DOMAIN, {}).get("exterior_track_linker")
            t = lk.find_owning_track(cam_key, "person", now) if lk is not None else None
            cls = lk.classify(t) if t is not None else None
        except Exception:  # noqa: BLE001
            cls = None
        return cls in ("approach", "circling")

    @staticmethod
    def _demote(severity: Severity) -> Severity:
        return max(Severity.LOW, min(severity, Severity.LOW))

    def _families_live(self, cam_key: str) -> set[str]:
        """NVR families with >=1 subscribed person leg whose state is live."""
        out: set[str] = set()
        for eid in self._person_legs_by_key.get(cam_key, set()):
            try:
                st = self.hass.states.get(eid)
                val = getattr(st, "state", None) if st is not None else None
            except Exception:  # noqa: BLE001
                val = None
            if not isinstance(val, str) or val in ("unavailable", "unknown", ""):
                continue
            out.add(nvr_family(self._sensor_engine.get(eid)))
        return out

    def _other_family_fire_since(
        self, cam_key: str, family: str, since_ts: float,
    ) -> bool:
        try:
            for eng, ts in self._recent_fires.get(cam_key, []):
                if ts.timestamp() < since_ts:
                    continue
                f = nvr_family(eng)
                if f in ("frigate", "protect") and f != family:
                    return True
        except Exception:  # noqa: BLE001
            return False
        return False

    def _adjacent_activity(self, cam_key: str, now: datetime) -> bool:
        try:
            lk = self.hass.data.get(DOMAIN, {}).get("exterior_track_linker")
            if lk is not None and hasattr(lk, "has_recent_adjacent_activity"):
                return bool(lk.has_recent_adjacent_activity(
                    cam_key, float(self._SOLE_FIRE_WINDOW_S), now,
                ))
        except Exception:  # noqa: BLE001
            return False
        return False

    def _prior_alerts_in_window(self, cam_key: str, now: datetime) -> int:
        """D5 (rev 2, H2): counted here, NOT read off the burst decision."""
        cutoff = now.timestamp() - float(PERIMETER_BURST_WINDOW_S)
        try:
            return sum(
                1 for ts in self._recent_alerts_by_camera.get(cam_key, [])
                if ts.timestamp() >= cutoff
            )
        except Exception:  # noqa: BLE001
            return 0

    async def _async_hold(self, cooldown_key: str, seconds: float) -> bool:
        """Hold the dispatch for `seconds` with the in-flight key ALREADY
        added by the caller (rev 2, H1). Discharges: the tracked timer,
        teardown (resolves the future), HA stopping. Returns True when the
        caller may proceed; on False / exception the key is released."""
        try:
            if seconds > 0:
                loop = asyncio.get_running_loop()
                fut = loop.create_future()

                @callback
                def _release(_now: Any = None) -> None:
                    if not fut.done():
                        fut.set_result(None)

                unsub = async_call_later(self.hass, seconds, _release)
                self._pending_holds[cooldown_key] = (unsub, fut)
                try:
                    await fut
                finally:
                    self._pending_holds.pop(cooldown_key, None)
        except BaseException:
            self._dispatch_in_flight.discard(cooldown_key)
            raise
        ok = self._active and not getattr(self.hass, "is_stopping", False)
        if not ok:
            self._dispatch_in_flight.discard(cooldown_key)
        return ok

    # ---- D3 -----------------------------------------------------------
    def _apply_zone_agreement_gate(
        self, cam_key: str, entity_id: str, now: datetime,
        severity: Severity, exemption_active: bool,
    ) -> Severity:
        try:
            cam = self._sensor_to_camera.get(entity_id, "")
            zones = self._zoned_cameras.get(cam)
            if not zones:
                return severity  # unzoned camera: never qualifies, no record
            infos = [self._zone_map[z] for z in zones if z in self._zone_map]
            frigate_name = infos[0]["frigate_name"] if infos else ""
            wanted = {i["zone_slug"] for i in infos}
            enforce = bool(self._options_flag(
                CONF_PERIMETER_ZONE_AGREEMENT_DEMOTE,
                DEFAULT_PERIMETER_ZONE_AGREEMENT_DEMOTE,
            ))
            d: dict[str, Any] = {
                "gate": "zone_agreement", "at": now.isoformat(),
                "entity_id": entity_id, "enforce": enforce,
                "would_demote": False, "demoted": False, "reason": "",
                "severity_before": severity.name,
            }
            rec = self._frigate_event_cache.get(frigate_name)
            entered = rec.get("entered_zones") if rec else None
            age = None
            if rec and isinstance(rec.get("received_at"), datetime):
                age = abs((now - rec["received_at"]).total_seconds())
            d["inputs"] = {"frigate_name": frigate_name, "zones": sorted(wanted),
                           "entered_zones": entered, "event_age_s": age}
            if entity_id in zones:
                # Review A-M2: the edge IS the property zone sensor — being in
                # the zone is the evidence; the shared per-camera cache may
                # hold an older/other object's record. Never demote.
                d["reason"] = "zone_leg_edge"
            elif PERIMETER_ZONE_AGREEMENT_MAX_AGE_S <= 0:
                d["reason"] = "disabled"
            elif self._exemption_shields(cam_key, now, exemption_active):
                d["reason"] = "classification_transition_exemption"
            elif rec is None or age is None:
                d["reason"] = "no_frigate_event"
            elif age > PERIMETER_ZONE_AGREEMENT_MAX_AGE_S:
                d["reason"] = "stale_event"
            elif not isinstance(entered, list):
                d["reason"] = "entered_zones_missing"
            elif any(zone_slug(z) in wanted for z in entered):
                d["reason"] = "in_zone"
            else:
                d["would_demote"] = True
                d["reason"] = "outside_property_zone"
                if enforce:
                    new = self._demote(severity)
                    d["demoted"] = new != severity
                    severity = new
            d["severity_after"] = severity.name
            self._record_gate(cam_key, d)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("PerimeterAlertManager: D3 raised (fail-open)", exc_info=True)
        return severity

    # ---- D5 -----------------------------------------------------------
    async def _apply_single_source_gate(
        self, cam_key: str, entity_id: str, now: datetime,
        severity: Severity, exemption_active: bool,
    ) -> tuple[Severity, bool, bool]:
        """Return (severity, held, proceed)."""
        held = False
        d: dict[str, Any] = {
            "gate": "single_source", "at": now.isoformat(),
            "entity_id": entity_id, "would_demote": False, "demoted": False,
            "reason": "", "severity_before": severity.name,
        }
        try:
            enforce = bool(self._options_flag(
                CONF_PERIMETER_SINGLE_SOURCE_DEMOTE,
                DEFAULT_PERIMETER_SINGLE_SOURCE_DEMOTE,
            ))
            d["enforce"] = enforce
            family = nvr_family(self._sensor_engine.get(entity_id))
            live = self._families_live(cam_key)
            both = {"frigate", "protect"} <= live
            lookback_from = now.timestamp() - float(self._SOLE_FIRE_WINDOW_S)
            seen_back = self._other_family_fire_since(cam_key, family, lookback_from)
            if both and family in ("frigate", "protect"):
                self._agreement_open(cam_key, family, now, seen_back)
            samples = self._agreement.samples(cam_key)
            rate = self._agreement.rate(cam_key)
            prior = self._prior_alerts_in_window(cam_key, now)
            min_samples = max(1, int(PERIMETER_SS_MIN_SAMPLES))
            d["inputs"] = {"families_live": sorted(live), "samples": samples,
                           "agreement_rate": rate, "prior_alerts": prior,
                           "other_family_lookback": seen_back}
            if self._exemption_shields(cam_key, now, exemption_active):
                d["reason"] = "classification_transition_exemption"
            elif not both:
                d["reason"] = "single_nvr"
            elif samples < min_samples or rate is None or rate < PERIMETER_SS_MIN_AGREEMENT:
                d["reason"] = "not_eligible"
            elif prior > 0:
                d["reason"] = "not_first_alert"
            elif seen_back:
                d["reason"] = "corroborated_lookback"
            else:
                d["would_demote"] = True
                if not enforce:
                    d["reason"] = "shadow"
                else:
                    # H1: in-flight BEFORE the await so the sibling engine's
                    # edge cannot start a parallel dispatch.
                    self._dispatch_in_flight.add(cam_key)
                    held = True
                    if not await self._async_hold(cam_key, float(PERIMETER_SS_SETTLE_S)):
                        d["reason"] = "dropped_teardown"
                        self._record_gate(cam_key, d)
                        return severity, True, False
                    if self._other_family_fire_since(cam_key, family, lookback_from):
                        d["would_demote"] = False
                        d["reason"] = "corroborated_settle"
                    elif self._adjacent_activity(cam_key, dt_util.now()):
                        d["would_demote"] = False
                        d["reason"] = "adjacent_activity"
                    else:
                        new = self._demote(severity)
                        d["demoted"] = new != severity
                        d["reason"] = "single_source"
                        severity = new
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.debug("PerimeterAlertManager: D5 raised (fail-open)", exc_info=True)
        d["severity_after"] = severity.name
        self._record_gate(cam_key, d)
        return severity, held, True

    # D5 tracker plumbing ------------------------------------------------
    def _agreement_open(
        self, cam_key: str, family: str, now: datetime, seen_back: bool,
    ) -> None:
        self._agreement.open_sample(cam_key, now, family, seen_back)
        self._agreement_schedule()

    def _agreement_note_fire(self, cam_key: str, engine: str, ts: datetime) -> None:
        try:
            self._agreement.note_fire(cam_key, nvr_family(engine), ts)
            if self._agreement.finalize_due(ts):
                self._agreement_save()
        except Exception:  # noqa: BLE001
            pass

    def _agreement_schedule(self) -> None:
        if self._unsub_agreement_timer is not None or not self._agreement.has_pending:
            return
        try:
            self._unsub_agreement_timer = async_call_later(
                self.hass, float(self._SOLE_FIRE_WINDOW_S) + 1.0,
                self._on_agreement_timer,
            )
        except Exception:  # noqa: BLE001
            self._unsub_agreement_timer = None

    @callback
    def _on_agreement_timer(self, _now: Any = None) -> None:
        self._unsub_agreement_timer = None
        try:
            if self._agreement.finalize_due(dt_util.now()):
                self._agreement_save()
        except Exception:  # noqa: BLE001
            pass
        if self._active:
            self._agreement_schedule()

    async def _async_load_agreement(self) -> None:
        """Load failure / corrupt store -> empty tracker (not eligible)."""
        try:
            from homeassistant.helpers.storage import Store  # noqa: PLC0415
            self._agreement_store = Store(
                self.hass, 1, f"{DOMAIN}.perimeter_agreement",
            )
            data = await self._agreement_store.async_load()
            self._agreement_load_ok = (
                self._agreement.load_dict(data) if data is not None else True
            )
        except Exception:  # noqa: BLE001
            self._agreement_load_ok = False
            _LOGGER.debug("PerimeterAlertManager: agreement store load failed",
                          exc_info=True)

    def _agreement_save(self) -> None:
        if self._agreement_store is None:
            return
        try:
            self._agreement_store.async_delay_save(
                self._agreement.to_dict, PERIMETER_AGREEMENT_SAVE_DELAY_S,
            )
        except Exception:  # noqa: BLE001
            pass

    # ---- D6 -----------------------------------------------------------
    def _vlm_gate_mode(self) -> str:
        return str(self._options_flag(CONF_PERIMETER_VLM_GATE, DEFAULT_PERIMETER_VLM_GATE))

    def _apply_vlm_gate(
        self, cam_key: str, entity_id: str, severity: Severity, verdict: str,
        snapshot_path: str | None, exemption_active: bool, mode: str,
    ) -> Severity:
        try:
            now = dt_util.now()
            ledger = self._last_snapshot_capture.get(
                _sanitize_snapshot_token(cam_key) or "camera"
            ) or {}
            tier = ledger.get("engine") if (
                snapshot_path and ledger.get("path") == snapshot_path
            ) else None
            d: dict[str, Any] = {
                "gate": "vlm", "at": now.isoformat(), "entity_id": entity_id,
                "mode": mode, "verdict": verdict, "tier": tier,
                "would_demote": False, "demoted": False, "reason": "",
                "severity_before": severity.name,
            }
            if verdict != VERDICT_NO:
                d["reason"] = "verdict_not_no"
            elif tier not in PERIMETER_VLM_TRUSTED_TIERS:
                d["reason"] = "untrusted_tier"
            elif self._exemption_shields(cam_key, now, exemption_active):
                d["reason"] = "classification_transition_exemption"
            else:
                d["would_demote"] = True
                d["reason"] = "vlm_no_person"
                if mode == PERIMETER_VLM_GATE_ENFORCE:
                    new = self._demote(severity)
                    d["demoted"] = new != severity
                    severity = new
            d["severity_after"] = severity.name
            self._record_gate(cam_key, d)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("PerimeterAlertManager: D6 raised (fail-open)", exc_info=True)
        return severity

    # ---- D10 ----------------------------------------------------------
    def _note_egress_stamp(self, entity_id: str, ts: datetime) -> None:
        cam = self._sensor_to_camera.get(entity_id, entity_id)
        self._last_egress_time_by_camera[cam] = ts

    def _is_dual_role_sensor(self, entity_id: str) -> bool:
        return self._sensor_to_camera.get(entity_id, "") in self._dual_role_cameras

    def _egress_stamp_for(self, entity_id: str) -> datetime | None:
        """INV-EGRESS-SELF: perimeter-only alert -> the global stamp (today);
        dual-role alert -> newest stamp from a NON-dual-role egress camera."""
        if not self._is_dual_role_sensor(entity_id):
            return self._last_egress_time
        stamps = [
            ts for cam, ts in self._last_egress_time_by_camera.items()
            if cam not in self._dual_role_cameras
        ]
        return max(stamps) if stamps else None

    def _egress_key(self, egress_camera: str) -> str:
        if not egress_camera:
            return ""
        if egress_camera.startswith("binary_sensor."):
            return self._camera_key_for_sensor(egress_camera) or ""
        if egress_camera.startswith("camera."):
            st = self._camera_slug_stem(egress_camera)
            return _EXTERIOR_CAMERA_KEY_ALIASES_LC.get(st, st)
        st = egress_camera.lower()
        return _EXTERIOR_CAMERA_KEY_ALIASES_LC.get(st, st)

    def _note_egress_identity(self, data: dict) -> None:
        try:
            pid = data.get("person_id")
            conf = data.get("identity_confidence")
            if not pid or conf is None:
                return
            key = self._egress_key(str(data.get("egress_camera") or ""))
            ts = dt_util.parse_datetime(str(data.get("timestamp"))) if hasattr(
                dt_util, "parse_datetime") else None
            if not key or ts is None:
                return
            lst = [e for e in self._recent_egress_identity.get(key, [])
                   if abs((ts - e[0]).total_seconds()) <= 600]
            lst.append((ts, str(pid), float(conf)))
            self._recent_egress_identity[key] = lst[-16:]
        except Exception:  # noqa: BLE001
            _LOGGER.debug("PerimeterAlertManager: egress identity cache failed",
                          exc_info=True)

    def _known_identity_for(
        self, cam_key: str, edge: datetime,
    ) -> tuple[str, float, str] | None:  # noqa: C901
        """D10.5: a KNOWN identity freshness-matched to this edge, at >= the
        doctrine floor (manual §5.5(a): >= 0.9). Sources: the egress bus
        event (detection timestamp within ±MATCH_S) and face legs whose
        last_changed is at/after edge-MATCH_S. A leg with no timestamp is
        NOT fresh here (H4). Frigate legs carry no score -> 0.60 -> unknown."""
        if float(PERIMETER_EGRESS_KNOWN_MIN_CONF) > 1.0:
            return None  # documented kill: > 1 disables the known-person demote
        floor = max(0.9, float(PERIMETER_EGRESS_KNOWN_MIN_CONF))
        match_s = float(PERIMETER_EGRESS_IDENTITY_MATCH_S)
        census = self.hass.data.get(DOMAIN, {}).get("census")
        known: set[str] = set()
        try:
            if census is not None:
                known |= {s.lower() for s in census._get_tracked_person_slugs()}
                for g in census._get_known_face_guests():
                    try:
                        known.add(census._canonical_person_slug(g) or str(g).lower())
                    except Exception:  # noqa: BLE001
                        known.add(str(g).lower())
        except Exception:  # noqa: BLE001
            pass
        if not known:
            return None
        best: tuple[str, float, str] | None = None
        for ts, pid, conf in self._recent_egress_identity.get(cam_key, []):
            try:
                if abs((edge - ts).total_seconds()) > match_s:
                    continue
            except Exception:  # noqa: BLE001
                continue
            if pid.lower() in known and conf >= floor and (best is None or conf > best[1]):
                best = (pid.lower(), conf, "egress_event")
        try:
            legs = census._resolve_face_legs(cam_key) if census is not None else []
        except Exception:  # noqa: BLE001
            legs = []
        for leg in legs or []:
            slug = (getattr(leg, "canonical_slug", None) or "").lower()
            lc = getattr(leg, "last_changed", None)
            c = getattr(leg, "confidence", None)
            if not slug or slug not in known or lc is None:
                continue
            try:
                if (lc - edge).total_seconds() < -match_s:
                    continue
            except Exception:  # noqa: BLE001
                continue
            if c is not None and c >= floor:
                if best is None or c > best[1]:
                    best = (slug, float(c), "face_leg")
                continue
            # Operator 2026-11-08: a below-floor face (Frigate, unscored =
            # 0.60) clears the §5.5(a) bar ONLY with an independent non-face
            # signal for the SAME person in the window.
            src = self._nonface_agrees(slug, edge, cam_key)
            if src and best is None:
                best = (slug, floor, f"face+{src}")
        return best

    def _nonface_agrees(
        self, slug: str, edge: datetime, cam_key: str = "",
    ) -> str | None:
        """A real ARRIVAL of `slug` near `edge` from an existing non-face
        signal (review B-MED-2). Either:
          - person tracker: a LIVE not_home -> home edge (listener-recorded,
            `_on_person_arrival_event`) within the window; or
          - Bermuda: PersonCoordinator moved the person INTO an area at or
            near this egress camera (`_near_areas`) within the window.
        Both ignore transitions inside PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S
        after setup (restore stamps last_changed at boot). Returns the source
        name or None. Window <= 0 disables (review A-L2)."""
        win = float(PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S)
        if win <= 0:
            return None
        boot_end = (self._fp_setup_ts or 0.0) + float(PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S)
        # LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1: the rule lives in the
        # shared arrival_edges module (also used by the SC lock regime).
        return nonface_arrival_source(
            slug=slug,
            at_ts=edge.timestamp(),
            window_s=win,
            boot_end=boot_end,
            tracker_arrivals=self._person_arrivals,
            pc_data_fn=lambda: getattr(
                self.hass.data.get(DOMAIN, {}).get("person_coordinator"), "data", None),
            areas_fn=lambda: self._near_areas(cam_key),
        )

    def _tracked_person_slugs(self) -> list[str]:
        try:
            raw = self._get_integration_config().get("tracked_persons", []) or []
            return [str(p).replace("person.", "").strip().lower() for p in raw if p]
        except Exception:  # noqa: BLE001
            return []

    @callback
    def _on_person_arrival_event(self, event: Any) -> None:
        """Record a live not_home -> home edge (old_state None = restore,
        not an arrival). Boot exclusion is applied at read time."""
        try:
            slug = live_arrival_slug(event.data)
            if slug:
                self._person_arrivals[slug] = dt_util.now().timestamp()
        except Exception:  # noqa: BLE001
            pass

    def _area_of_entity(self, entity_id: str) -> str:
        """HA area name (slugged) of an entity via entity/device registry."""
        return area_slug_of_entity(self.hass, entity_id)

    def _near_areas(self, cam_key: str) -> set[str]:
        """Areas at/near a dual-role egress camera: the camera's own area,
        plus the areas of its EXPLICITLY configured door-interior neighbours
        (transit_validator door groups; the unset fallback of 'every
        interior camera' is NOT used here — too wide for an arrival)."""
        out: set[str] = set()
        cams = [c for c in self._dual_role_cameras
                if self._camera_key_for_sensor(
                    f"binary_sensor.{self._camera_slug_stem(c)}_person_detected") == cam_key
                or self._camera_slug_stem(c) == cam_key]
        for c in cams:
            a = self._area_of_entity(c)
            if a:
                out.add(a)
        try:
            tv = self.hass.data.get(DOMAIN, {}).get("transit_validator")
            if tv is not None:
                group = tv._door_group_for_stem(cam_key)
                nb = getattr(tv, "_interior_neighbours_by_group", {}) or {}
                if group is not None and group in nb:
                    for n in nb[group]:
                        a = self._area_of_entity(n)
                        if a:
                            out.add(a)
        except Exception:  # noqa: BLE001
            pass
        out.discard("")
        return out

    async def _apply_egress_identity_gate(
        self, cam_key: str, entity_id: str, now: datetime,
        severity: Severity, exemption_active: bool,
    ) -> tuple[Severity, bool, bool]:
        """D10.5 table (demote-only). Return (severity, held, proceed)."""
        held = False
        d: dict[str, Any] = {
            "gate": "egress_identity", "at": now.isoformat(),
            "entity_id": entity_id, "demoted": False, "reason": "",
            "severity_before": severity.name,
        }
        try:
            if not bool(self._options_flag(
                CONF_PERIMETER_EGRESS_KNOWN_XCORR_GATE,
                DEFAULT_PERIMETER_EGRESS_KNOWN_XCORR_GATE,
            )):
                d["reason"] = "gate_off"
                self._record_gate(cam_key, d)
                return severity, False, True
            if self._exemption_shields(cam_key, now, exemption_active):
                d["reason"] = "classification_transition_exemption"
                self._record_gate(cam_key, d)
                return severity, False, True
            family = nvr_family(self._sensor_engine.get(entity_id))
            since = now.timestamp() - float(self._SOLE_FIRE_WINDOW_S)
            known = self._known_identity_for(cam_key, now)
            if known is None and PERIMETER_EGRESS_IDENTITY_WAIT_S > 0:
                self._dispatch_in_flight.add(cam_key)
                held = True
                if not await self._async_hold(cam_key, float(PERIMETER_EGRESS_IDENTITY_WAIT_S)):
                    d["reason"] = "dropped_teardown"
                    self._record_gate(cam_key, d)
                    return severity, True, False
                known = self._known_identity_for(cam_key, now)
            second_live = {"frigate", "protect"} <= self._families_live(cam_key)
            corroborated = self._other_family_fire_since(cam_key, family, since) or (
                self._adjacent_activity(cam_key, dt_util.now())
            )
            # Unknown + uncorroborated + second NVR live: a bounded
            # corroboration settle (own knob, review A-M4) before demoting,
            # so the other engine's edge a little later still counts.
            if known is None and second_live and not corroborated and PERIMETER_EGRESS_XCORR_SETTLE_S > 0:
                if not held:
                    self._dispatch_in_flight.add(cam_key)
                    held = True
                if not await self._async_hold(cam_key, float(PERIMETER_EGRESS_XCORR_SETTLE_S)):
                    d["reason"] = "dropped_teardown"
                    self._record_gate(cam_key, d)
                    return severity, True, False
                corroborated = self._other_family_fire_since(cam_key, family, since) or (
                    self._adjacent_activity(cam_key, dt_util.now())
                )
                known = known or self._known_identity_for(cam_key, now)
            d["inputs"] = {"known": known, "second_leg_live": second_live,
                           "corroborated": corroborated}
            if known is not None:
                d["reason"] = "egress_known_person"
                new = self._demote(severity)
            elif not second_live:
                d["reason"] = "xcorr_waived_single_nvr"
                new = severity
            elif corroborated:
                d["reason"] = "egress_unknown_corroborated"
                new = severity
            else:
                d["reason"] = "egress_uncorroborated"
                new = self._demote(severity)
            d["demoted"] = new != severity
            severity = new
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.debug("PerimeterAlertManager: D10.5 raised (fail-open)", exc_info=True)
        d["severity_after"] = severity.name
        self._record_gate(cam_key, d)
        return severity, held, True

    # ------------------------------------------------------------------
    # PERIMETER-IDENTITY-FOLLOWUP-1 (v5.107.5): "that was <name>"
    # ------------------------------------------------------------------
    _FOLLOWUP_UNKNOWN_REASONS = frozenset(
        {"egress_unknown_corroborated", "xcorr_waived_single_nvr"}
    )
    FOLLOWUP_TITLE = "Perimeter Alert — Identified"

    def _cancel_identity_followup(self, cam_key: str, reason: str) -> None:
        st = self._pending_followups.pop(cam_key, None)
        if st is None:
            return
        unsub = st.get("unsub")
        st["unsub"] = None
        if unsub is not None:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        _LOGGER.debug("PerimeterAlertManager: identity follow-up for %s "
                      "discharged (%s)", cam_key, reason)

    def _arm_identity_followup(
        self, cam_key: str, entity_id: str, edge: datetime,
        severity: Severity, annotated: str | None,
    ) -> bool:
        """Arm a bounded follow-up after a dispatched alert. Only when the
        D10.5 decision for THIS alert (same edge) said unknown and did not
        demote, the dispatched severity is above LOW and still equals the
        D10.5 output (a later VLM demote counts as demoted), and the message
        carried no identity annotation. Any previous follow-up on the key is
        superseded first. Returns True when armed."""
        self._cancel_identity_followup(cam_key, "superseded")
        try:
            if not self._active:
                return False
            if not bool(self._options_flag(
                CONF_PERIMETER_IDENTITY_FOLLOWUP,
                DEFAULT_PERIMETER_IDENTITY_FOLLOWUP,
            )):
                return False
            if float(PERIMETER_IDENTITY_FOLLOWUP_WINDOW_S) <= 0:
                return False
            if severity <= Severity.LOW or annotated:
                return False
            d = (self._last_gate_decisions.get(cam_key) or {}).get(
                "egress_identity") or {}
            if (
                d.get("at") != edge.isoformat()
                or d.get("demoted")
                or d.get("reason") not in self._FOLLOWUP_UNKNOWN_REASONS
                or d.get("severity_after") != severity.name
            ):
                return False
            state: dict[str, Any] = {
                "edge": edge, "entity_id": entity_id, "severity": severity,
                "elapsed": 0.0, "unsub": None,
            }
            self._pending_followups[cam_key] = state
            self._schedule_followup_tick(cam_key, state)
            return True
        except Exception:  # noqa: BLE001
            _LOGGER.debug("PerimeterAlertManager: follow-up arm failed",
                          exc_info=True)
            self._pending_followups.pop(cam_key, None)
            return False

    def _schedule_followup_tick(self, cam_key: str, state: dict[str, Any]) -> None:
        window = float(PERIMETER_IDENTITY_FOLLOWUP_WINDOW_S)
        delay = max(0.0, min(float(PERIMETER_IDENTITY_FOLLOWUP_POLL_S),
                             window - state["elapsed"]))

        @callback
        def _tick(_now: Any) -> None:
            if self._pending_followups.get(cam_key) is not state:
                return  # discharged / superseded
            state["unsub"] = None
            state["elapsed"] += delay
            self._followup_check(cam_key, state)

        state["unsub"] = async_call_later(self.hass, delay, _tick)

    def _followup_check(self, cam_key: str, state: dict[str, Any]) -> None:
        if not self._active:
            self._cancel_identity_followup(cam_key, "inactive")
            return
        try:
            known = self._known_identity_for(cam_key, state["edge"])
        except Exception:  # noqa: BLE001
            known = None
        if known is not None:
            # Pop BEFORE sending: at most one follow-up per alert.
            self._pending_followups.pop(cam_key, None)
            self._record_gate(cam_key, {
                "gate": "identity_followup", "at": state["edge"].isoformat(),
                "sent_after_s": state["elapsed"], "identity": known[0],
                "source": known[2],
            })
            self.hass.async_create_task(
                self._async_send_identity_followup(state, known[0])
            )
            return
        if state["elapsed"] >= float(PERIMETER_IDENTITY_FOLLOWUP_WINDOW_S):
            self._cancel_identity_followup(cam_key, "window_expired")
            return
        self._schedule_followup_tick(cam_key, state)

    def _followup_camera_name(self, entity_id: str, cam_key: str) -> str:
        cam = self._sensor_to_camera.get(entity_id, "")
        try:
            st = self.hass.states.get(cam) if cam else None
            fn = st.attributes.get("friendly_name") if st is not None else None
            if isinstance(fn, str) and fn.strip():
                return fn.strip()
        except Exception:  # noqa: BLE001
            pass
        return cam_key.replace("_", " ").title()

    def _followup_person_name(self, slug: str) -> str:
        try:
            st = self.hass.states.get(f"person.{slug}")
            fn = st.attributes.get("friendly_name") if st is not None else None
            if isinstance(fn, str) and fn.strip():
                return fn.strip()
        except Exception:  # noqa: BLE001
            pass
        return slug.replace("_", " ").title()

    async def _async_send_identity_followup(
        self, state: dict[str, Any], slug: str,
    ) -> None:
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if not self._active or nm is None or not getattr(nm, "enabled", False):
            return
        entity_id = state["entity_id"]
        cam_key = self._camera_key_for_sensor(entity_id) or entity_id
        message = (f"{self._followup_camera_name(entity_id, cam_key)}: "
                   f"that was {self._followup_person_name(slug)}")
        try:
            await nm.async_notify(
                coordinator_id="perimeter_alert",
                severity=state["severity"],
                title=self.FOLLOWUP_TITLE,
                message=message,
                hazard_type=NM_HAZARD_EXTERIOR_PERSON,
                location=entity_id,
                quiet=True,
            )
            _LOGGER.info("PerimeterAlertManager: identity follow-up sent "
                         "for %s: %s", entity_id, message)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("PerimeterAlertManager: identity follow-up failed "
                          "for %s: %s", entity_id, exc)

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

    def _get_notify_config(self) -> tuple[str | None, str | None]:
        """Return (notify_service, notify_target). CONSOL-1 §D1 retired
        the legacy notify leg; this helper only reads the RETIRED keys
        so the setup-time deprecation ERROR can detect operators still
        carrying old options blobs (§D1 test hook)."""
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

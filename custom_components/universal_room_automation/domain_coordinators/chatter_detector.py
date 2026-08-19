"""ChatterDetector — physics-based sensor chatter (STEP D2 + D3).

See ``docs/planning/PLANNING_sensor_health_surfacing.md`` §D2/§D3
and ``docs/planning/PROBE_sensor_chatter_definition_handcheck.md``
for the grounded definition.

Chatter is *quarantine-ALWAYS* on a physics violation a correctly-working
sensor CANNOT satisfy. No corroborator gate. The definition:

    A blind-time-gated sensor (per CHATTER_PROVENANCE_ALLOWLIST) is
    chattering iff it emits >= CHATTER_BURST_K transitions whose interval
    since the prior transition is BELOW that sensor's per-family
    T_floor ("impossibility events") within the rolling
    CHATTER_OBSERVATION_WINDOW_S window.

The detector:

  * registers its OWN ``async_track_state_change_event`` listener over
    the room's blind-time-gated tier-1 entities (Option 1 in the plan
    resolution 2026-08-19 — occupancy_substrate.subscribe() is per-kind
    aggregate and cannot drive per-entity bursts).
  * on each edge: guards unavailable/unknown; classifies (kind, provider)
    via CHATTER_PROVENANCE_ALLOWLIST + camera-family regex fallback;
    tracks sub-T_floor "impossibility events" in a rolling deque per
    entity; marks the entity chattering when the burst count crosses K.
  * exposes ``check(exclusion_set)`` for the tick site to mirror-promote
    into the shared SensorExclusionSet, and ``check_release(...)`` for
    auto-release after CHATTER_RELEASE_QUIET_S of zero transitions.
  * teardown drains the listener (Bug Class #38 discipline — the unsub
    is stored as ``self._chatter_unsub`` and released from
    ``async_teardown()`` called out of ``__init__.py`` async_unload_entry,
    mirroring the actuator_reconciler pattern).

_entity_to_kind refresh note: the entity_id -> kind map is rebuilt on
every ``async_register_listeners()`` call. A room-entry reload tears the
detector down and constructs a fresh one via the coordinator's rebuild
hook (``_update_signal_subscriptions``), so the map cannot cache beyond
one setup — a config change that adds/removes a sensor picks up the new
mapping on the very next rebuild. Do NOT hoist this map into __init__
or module scope; it must live per-setup.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Callable, Deque, Dict, Optional, Set, Tuple

from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from ..const import (
    CHATTER_BURST_K,
    CHATTER_CAMERA_FAMILY_ENTITY_SUBSTRINGS,
    CHATTER_CAMERA_FAMILY_INTEGRATIONS,
    CHATTER_OBSERVATION_WINDOW_S,
    CHATTER_PROVENANCE_ALLOWLIST,
    CHATTER_PROVENANCE_DENYLIST,
    CHATTER_RELEASE_QUIET_S,
    CHATTER_T_FLOOR_DEFAULTS,
    CONF_CHATTER_BURST_K,
    CONF_CHATTER_T_FLOOR_S,
    CONF_MMWAVE_SENSORS,
    CONF_MOTION_SENSORS,
    CONF_OCCUPANCY_SENSORS,
    DEFAULT_CHATTER_BURST_K,
    DEFAULT_CHATTER_T_FLOOR_S,
)

_LOGGER = logging.getLogger(__name__)

# Kind bucket labels — mirror occupancy_substrate._KIND_TO_CONF plus the
# "opener" kind that lives outside the substrate's motion/mmwave/occupancy
# taxonomy (garage door + reed switches; blind-time-gated by hardware).
_CONF_TO_KIND: Dict[str, str] = {
    CONF_MOTION_SENSORS: "motion",
    CONF_MMWAVE_SENSORS: "mmwave",
    CONF_OCCUPANCY_SENSORS: "occupancy",
}

# entity_id substring hints used when no explicit capability provider tag
# is available. Order matters: check ratgdo BEFORE the bare "motion" hint.
_PROVIDER_SUBSTRINGS: Tuple[Tuple[str, str], ...] = (
    ("ratgdov", "ratgdo"),
    ("ratgdo", "ratgdo"),
    ("garage_door", "garage_door"),
    ("mmwave", "mmwave"),
    ("presence", "mmwave"),
    ("_pir", "pir"),
    ("zigbee", "zigbee_pir"),
    # Broadest fallback for entities named `..._motion` when no capability
    # provider tag is available: assume PIR. Safe because the camera-family
    # regex (checked BEFORE this fallback in _classify) already denies
    # camera / frigate / unifi_protect / binarygroup_camera_* by name.
    ("_motion", "pir"),
)

# T_floor family lookup: (kind, provider) -> family key in
# CHATTER_T_FLOOR_DEFAULTS. Any (kind, provider) not covered here falls
# back to the family that matches the provider prefix; if nothing matches
# the entity is not scored (T_floor = 0 semantics).
def _t_floor_for(kind: str, provider: str) -> float:
    p = provider.lower()
    if p.startswith("mmwave"):
        return CHATTER_T_FLOOR_DEFAULTS["mmwave"]
    if p in ("ratgdo", "garage_door"):
        return CHATTER_T_FLOOR_DEFAULTS["opener"]
    if p.endswith("reed") or p == "reed":
        return CHATTER_T_FLOOR_DEFAULTS["reed"]
    if "pir" in p:
        return CHATTER_T_FLOOR_DEFAULTS["pir"]
    if kind == "opener":
        return CHATTER_T_FLOOR_DEFAULTS["opener"]
    if kind in ("motion", "occupancy"):
        return CHATTER_T_FLOOR_DEFAULTS["pir"]
    if kind in ("mmwave", "presence"):
        return CHATTER_T_FLOOR_DEFAULTS["mmwave"]
    return 0.0


# D-MED-1 fix (2026-08-19): Zigbee-native / Z2M-numeric integration
# platforms whose entities are legitimate blind-time-gated hardware but
# whose entity_id (e.g. `binary_sensor.0x00158d..._occupancy`) does NOT
# substring-match _PROVIDER_SUBSTRINGS. When the entity is on one of
# these platforms AND its device_class is a blind-time-gated kind, we
# infer provider from the device_class name.
_ZIGBEE_NATIVE_PLATFORMS: frozenset = frozenset({
    "zha",
    "zwave_js",
    "deconz",
    "mqtt",  # Z2M ships as MQTT
})

_DEVICE_CLASS_TO_PROVIDER: Dict[str, str] = {
    "motion": "zigbee_pir",
    "occupancy": "zigbee_mmwave",
    "presence": "zigbee_mmwave",
    "opening": "zigbee_reed",
    "door": "zigbee_reed",
    "window": "zigbee_reed",
    "garage_door": "garage_door",
}


def _is_camera_family(entity_id: str, integration: Optional[str]) -> bool:
    """Camera-family classifier — fires BEFORE the (kind, provider) allow-list.

    A mislabeled ``device_class=motion`` entity from a camera integration
    is denied here regardless of any (kind, provider) tag downstream.
    """
    if integration and integration.lower() in CHATTER_CAMERA_FAMILY_INTEGRATIONS:
        return True
    eid = entity_id.lower()
    for sub in CHATTER_CAMERA_FAMILY_ENTITY_SUBSTRINGS:
        if sub in eid:
            return True
    return False


def _classify(entity_id: str, kind: str, provider: Optional[str],
              integration: Optional[str],
              device_class: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Return ``(in_scope, provider_used)`` for chatter scoring.

    Silent-default DENY: any classification we're not confident in
    returns ``(False, provider_used)`` and the entity is never scored.
    """
    # Camera-family regex/integration guard fires FIRST (M-MED-2 defense
    # in depth). A camera-motion group with device_class=motion is denied
    # here even if the (kind, provider) lookup below would have allowed it.
    if _is_camera_family(entity_id, integration):
        return (False, provider)

    # Explicit denylist check.
    if provider and (kind, provider) in CHATTER_PROVENANCE_DENYLIST:
        return (False, provider)
    if (kind, "any") in CHATTER_PROVENANCE_DENYLIST:
        return (False, provider)

    # Explicit allow-list check.
    if provider and (kind, provider) in CHATTER_PROVENANCE_ALLOWLIST:
        return (True, provider)

    # Fallback: infer provider from entity_id substrings — only if the
    # inferred (kind, provider) IS on the allow-list. Silent-default DENY
    # otherwise.
    eid = entity_id.lower()
    for sub, inferred in _PROVIDER_SUBSTRINGS:
        if sub in eid and (kind, inferred) in CHATTER_PROVENANCE_ALLOWLIST:
            return (True, inferred)

    # D-MED-1 (2026-08-19): Zigbee-native fallback for numeric-id Z2M
    # entities. If the integration is one of the Zigbee-native platforms
    # AND the entity's device_class is a blind-time-gated kind, infer
    # provider from device_class. Preserves silent-default DENY for
    # anything that doesn't clearly resolve.
    if integration and integration.lower() in _ZIGBEE_NATIVE_PLATFORMS:
        if device_class:
            inferred = _DEVICE_CLASS_TO_PROVIDER.get(device_class.lower())
            if inferred and (kind, inferred) in CHATTER_PROVENANCE_ALLOWLIST:
                return (True, inferred)

    return (False, provider)


class ChatterDetector:
    """Per-room chatter detector — physics-based, corroborator-free."""

    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator
        self.hass: HomeAssistant = coordinator.hass
        self._room_name = "unknown"
        try:
            from ..const import CONF_ROOM_NAME  # noqa: PLC0415
            self._room_name = coordinator.entry.data.get(
                CONF_ROOM_NAME, "unknown",
            )
        except Exception:  # noqa: BLE001 — best-effort label
            pass

        # entity_id -> (kind, provider, T_floor). Rebuilt each
        # async_register_listeners() call — see module docstring.
        self._entity_to_meta: Dict[str, Tuple[str, str, float]] = {}

        # entity_id -> deque[timestamp_iso] of the LAST N transitions
        # (kept trimmed to the observation window). Also stores the
        # timestamp of the most-recent transition for release-quiet
        # bookkeeping via _last_edge_ts.
        self._edge_windows: Dict[str, Deque[datetime]] = {}
        self._sub_floor_events: Dict[str, Deque[datetime]] = {}
        self._last_edge_ts: Dict[str, datetime] = {}
        self._last_edge_state: Dict[str, str] = {}

        # Sticky book (release-quiet auto-clear works against this).
        self._chattering: Set[str] = set()
        # per-entity chatter-onset iso timestamp for the diagnostic surface.
        self._chatter_since: Dict[str, str] = {}

        # HA state-change listener unsub. Bug Class #38: stored on the
        # instance so async_teardown() can release it.
        self._chatter_unsub: Optional[Callable[[], None]] = None

    # ------------------------------------------------------------------
    # Setup / teardown lifecycle
    # ------------------------------------------------------------------

    def _iter_configured_entities(self) -> Set[Tuple[str, str]]:
        """Yield ``(entity_id, kind)`` for every tier-1 sensor in the room."""
        entries: Set[Tuple[str, str]] = set()
        config = getattr(self.coordinator, "entry", None)
        if config is None:
            return entries
        data = {**config.data, **config.options}
        for conf_key, kind in _CONF_TO_KIND.items():
            for eid in (data.get(conf_key) or []):
                if isinstance(eid, str) and eid:
                    entries.add((eid, kind))
        return entries

    def _resolve_provider(
        self, entity_id: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Return ``(provider, integration, device_class)`` best-effort.

        Provider = URA capability tag if the sensor_capability layer knows
        it; else None (classifier falls back to entity_id substring or
        D-MED-1 Zigbee-native device_class inference).
        Integration = HA entity-registry platform (used by the camera-
        family guard AND by the Zigbee-native fallback).
        device_class = entity-registry OR state-attribute device_class
        (used by the Zigbee-native fallback to infer provider from
        numeric-id Z2M entities).
        """
        provider: Optional[str] = None
        integration: Optional[str] = None
        device_class: Optional[str] = None
        # Best-effort provider from URA capability layer.
        try:
            from .sensor_capability import get_capability  # noqa: PLC0415
            cap = get_capability(self.hass, entity_id)
            if cap is not None:
                provider = getattr(cap, "provider", None) or getattr(
                    cap, "provider_tag", None,
                )
        except Exception:  # noqa: BLE001 — provider is best-effort
            provider = None
        # Entity-registry platform + device_class.
        try:
            from homeassistant.helpers import entity_registry as er  # noqa: PLC0415
            reg = er.async_get(self.hass)
            entry = reg.async_get(entity_id)
            if entry is not None:
                integration = entry.platform
                device_class = (
                    getattr(entry, "device_class", None)
                    or getattr(entry, "original_device_class", None)
                )
        except Exception:  # noqa: BLE001 — HA registry is best-effort
            integration = None
        # Fallback: live state attribute (some integrations set device_class
        # only on the state, not the registry entry).
        if device_class is None:
            try:
                st = self.hass.states.get(entity_id)
                if st is not None:
                    device_class = st.attributes.get("device_class")
            except Exception:  # noqa: BLE001
                device_class = None
        return provider, integration, device_class

    def _effective_t_floor_default(self) -> Optional[float]:
        """Return the operator-settable T_floor override, or None.

        D-MED-2 fix-up: options-flow override lives at
        CONF_CHATTER_T_FLOOR_S. When absent/invalid, we return None and
        the caller falls back to the per-family default.
        """
        try:
            from ._nm_cycle_a import nm_cycle_a_knob  # noqa: PLC0415
            v = nm_cycle_a_knob(
                self.hass, CONF_CHATTER_T_FLOOR_S, DEFAULT_CHATTER_T_FLOOR_S,
            )
            f = float(v)
            if f < 0.0:
                return None
            return f
        except Exception:  # noqa: BLE001
            return None

    def _effective_burst_k(self) -> int:
        """Return the operator-settable burst-K override, else the default."""
        try:
            from ._nm_cycle_a import nm_cycle_a_knob  # noqa: PLC0415
            v = nm_cycle_a_knob(
                self.hass, CONF_CHATTER_BURST_K, DEFAULT_CHATTER_BURST_K,
            )
            k = int(v)
            if k <= 0:
                return CHATTER_BURST_K
            return k
        except Exception:  # noqa: BLE001
            return CHATTER_BURST_K

    def async_register_listeners(self) -> None:
        """Register (or re-register) the per-entity state-change listener.

        Called from RoomCoordinator._update_signal_subscriptions rebuild
        hook — idempotent (drains any prior listener first). Mirrors the
        ActuatorReconciler pattern (Bug Class #38 + #50 discipline).

        Rebuilds ``_entity_to_meta`` from scratch each call so a
        config-change room-rebuild picks up new sensors on the very next
        rebuild — the map cannot go stale past one setup.
        """
        self._drain_listener()
        self._entity_to_meta = {}

        # D-MED-2 (2026-08-19): read operator-settable T_floor override
        # via nm_cycle_a_knob (rung 2). Falls back to the rung-1 default.
        # A per-sensor T_floor=0 still hard-kills that sensor's scoring.
        operator_t_floor = self._effective_t_floor_default()

        gated_entities: list[str] = []
        for eid, kind in self._iter_configured_entities():
            provider, integration, device_class = self._resolve_provider(eid)
            in_scope, provider_used = _classify(
                eid, kind, provider, integration, device_class,
            )
            if not in_scope:
                continue
            # Rung ordering: operator override (if set) overrides family
            # default. Per-entity sensor_capability override would sit
            # between operator and family — not wired here yet (parked;
            # no field evidence of a per-hardware need).
            t_floor = (
                operator_t_floor
                if operator_t_floor is not None
                else _t_floor_for(kind, provider_used or "")
            )
            if t_floor <= 0.0:
                # Per-sensor kill switch (T_floor=0 -> not scored).
                continue
            self._entity_to_meta[eid] = (kind, provider_used or "", t_floor)
            gated_entities.append(eid)

        if not gated_entities:
            _LOGGER.debug(
                "ChatterDetector[%s]: no blind-time-gated entities in scope; "
                "listener not armed",
                self._room_name,
            )
            return

        try:
            unsub = async_track_state_change_event(
                self.hass, gated_entities, self._on_edge,
            )
            self._chatter_unsub = unsub
            _LOGGER.info(
                "ChatterDetector[%s]: tracking %d blind-time-gated sensor(s) "
                "for physics-based chatter",
                self._room_name, len(gated_entities),
            )
        except Exception:  # noqa: BLE001 — defensive
            _LOGGER.warning(
                "ChatterDetector[%s]: state-change subscription failed",
                self._room_name, exc_info=True,
            )
            self._chatter_unsub = None

    def _drain_listener(self) -> None:
        if self._chatter_unsub is not None:
            try:
                self._chatter_unsub()
            except Exception:  # noqa: BLE001 — defensive teardown
                _LOGGER.debug(
                    "ChatterDetector[%s]: unsub raised during drain",
                    self._room_name, exc_info=True,
                )
            self._chatter_unsub = None

    async def async_teardown(self) -> None:
        """Release the listener + clear per-entity trackers.

        Called from __init__.py async_unload_entry (mirroring the
        actuator_reconciler pattern). Idempotent.
        """
        self._drain_listener()
        self._edge_windows.clear()
        self._sub_floor_events.clear()
        self._last_edge_ts.clear()
        self._last_edge_state.clear()
        # NOTE: _chattering + _chatter_since are intentionally cleared too;
        # RAM state does not survive reload/restart (matches the plan's
        # "restart -> chatter re-detected from live edges" semantics).
        self._chattering.clear()
        self._chatter_since.clear()

    # ------------------------------------------------------------------
    # Edge handler
    # ------------------------------------------------------------------

    def _on_edge(self, event: Event) -> None:
        """State-change callback — count sub-T_floor impossibility events.

        Fail-safe: any exception is caught and logged at debug. This
        callback runs on the event loop and must never raise.
        """
        try:
            entity_id = event.data.get("entity_id")
            new_state = event.data.get("new_state")
            if not entity_id or new_state is None:
                return
            meta = self._entity_to_meta.get(entity_id)
            if meta is None:
                return  # not in-scope this setup
            _kind, _provider, t_floor = meta
            if t_floor <= 0.0:
                return  # kill switch for this sensor

            state_val = new_state.state
            # Guard unavailable/unknown transitions — separate fault class,
            # NOT chatter (per plan §D2 algorithm step 2).
            if state_val in ("unavailable", "unknown"):
                return

            # De-duplicate same-value edges: HA fires state_changed even
            # for attribute-only changes on some platforms. Chatter is
            # about value oscillation.
            prev_state_val = self._last_edge_state.get(entity_id)
            if prev_state_val == state_val:
                return

            # D-HIGH-2 fix (2026-08-19): boot-settle gate MUST be checked
            # BEFORE the deque append. Otherwise a restart flurry
            # accumulates unbounded sub-floor events (deque is
            # observation-window-trimmed by wall-clock, not by
            # boot-settle) and the first post-settle edge sees len>=K ->
            # instant quarantine on every restart with motion.
            boot_settled = True
            try:
                boot_settled = bool(self.coordinator._d2_boot_settle_done())
            except Exception:  # noqa: BLE001
                boot_settled = True  # fail-open: still score
            if not boot_settled:
                # Drop the edge entirely — do NOT record last_edge_ts
                # either, so the first POST-settle edge does not compute
                # a spurious 0.001s "interval" against a pre-settle edge.
                return

            now = event.time_fired if event.time_fired is not None else dt_util.utcnow()
            prev_ts = self._last_edge_ts.get(entity_id)
            self._last_edge_ts[entity_id] = now
            self._last_edge_state[entity_id] = state_val

            # Append to rolling window; trim to observation window.
            window = self._edge_windows.setdefault(entity_id, deque())
            window.append(now)
            cutoff = now - timedelta(seconds=CHATTER_OBSERVATION_WINDOW_S)
            while window and window[0] < cutoff:
                window.popleft()

            # If prev_ts exists AND the interval was below the sensor's
            # T_floor -> this is an "impossibility event". Record it in
            # the sub-floor deque (also observation-window-scoped).
            if prev_ts is not None:
                interval = (now - prev_ts).total_seconds()
                if interval < t_floor:
                    sf = self._sub_floor_events.setdefault(entity_id, deque())
                    sf.append(now)
                    while sf and sf[0] < cutoff:
                        sf.popleft()

                    # Score: burst-of-K within window -> chatter.
                    burst_k = self._effective_burst_k()
                    if (
                        len(sf) >= burst_k
                        and entity_id not in self._chattering
                    ):
                        self._chattering.add(entity_id)
                        self._chatter_since[entity_id] = dt_util.utcnow().isoformat()
                        _LOGGER.info(
                            "ChatterDetector[%s]: %s FLAGGED chatter "
                            "(%d sub-%.1fs impossibility events in %ds window, K=%d)",
                            self._room_name, entity_id, len(sf),
                            t_floor, int(CHATTER_OBSERVATION_WINDOW_S), burst_k,
                        )
        except Exception:  # noqa: BLE001 — fail-safe on the hot path
            _LOGGER.debug(
                "ChatterDetector[%s]: edge handler raised (swallowed)",
                self._room_name, exc_info=True,
            )

    # ------------------------------------------------------------------
    # Tick-site consumption + auto-release (D3)
    # ------------------------------------------------------------------

    def chattering_entities(self) -> Set[str]:
        """Return the currently-flagged sensor set (snapshot copy)."""
        return set(self._chattering)

    def chatter_detail(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Return diagnostic detail for D5 surface, or None."""
        if entity_id not in self._chattering:
            return None
        return {
            "entity_id": entity_id,
            "reason": "chattering",
            "transition_count": len(self._edge_windows.get(entity_id, ())),
            "sub_floor_events": len(self._sub_floor_events.get(entity_id, ())),
            "since": self._chatter_since.get(entity_id),
        }

    def check_release(self, now: Optional[datetime] = None) -> Set[str]:
        """Release entities quiet for CHATTER_RELEASE_QUIET_S.

        Returns the set of released entity_ids so the caller can:
          (a) call ``exclusion_set.release("chatter", eid)`` for each, and
          (b) fire the paired recovered NM to clear the per-day latch.

        An entity currently unavailable/unknown is NOT released — quiet-
        on-dead-hardware != stability (matches actuator flap release rule).
        """
        if now is None:
            now = dt_util.utcnow()
        released: Set[str] = set()
        for eid in list(self._chattering):
            last = self._last_edge_ts.get(eid)
            if last is None:
                continue
            if (now - last).total_seconds() < CHATTER_RELEASE_QUIET_S:
                continue
            # Availability check.
            try:
                st = self.hass.states.get(eid)
                if st is None or st.state in ("unavailable", "unknown"):
                    continue
            except Exception:  # noqa: BLE001
                continue
            self._chattering.discard(eid)
            self._chatter_since.pop(eid, None)
            self._sub_floor_events.pop(eid, None)
            _LOGGER.info(
                "ChatterDetector[%s]: %s RELEASED from chatter "
                "(quiet for %.0fs, currently available)",
                self._room_name, eid, CHATTER_RELEASE_QUIET_S,
            )
            released.add(eid)
        return released

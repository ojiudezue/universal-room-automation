"""Person tracking coordinator for Universal Room Automation."""
#
# Universal Room Automation vv5.90.0
# Build: 2026-01-03
# File: person_coordinator.py
# v3.2.9: No changes (zone fixes in aggregation.py, fan fixes in automation.py)
# v3.2.8.3: Fixed previous_location_time to record when person LEFT (not when they entered)
# v3.2.8.1: Implemented staleness decay logic with tracking_status and recent_path
# v3.2.8.1: Fixed Previous Seen sensor to track previous_location_time separately
# NEW: Three-tier scanner resolution for room-level person tracking
#   - Tier 1: Direct HA area name match (zero config for dense scanner homes)
#   - Tier 2: CONF_SCANNER_AREAS override lookup (for sparse scanner homes)
#   - Tier 3: Occupancy disambiguation (when multiple rooms share a scanner)
# v3.2.8: Added support for active state change listeners in aggregation sensors
# FIX v3.2.6: Previous location bug - was reading from current dict instead of self.data
# FIX v3.2.6: Lowered confidence threshold from 0.5 to 0.3 for room occupant matching
# FIX v3.2.6: Added comprehensive diagnostic logging for room occupant matching
#

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.person import DOMAIN as PERSON_DOMAIN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry as er, device_registry as dr, area_registry as ar
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_TRACKED_PERSONS,
    CONF_PERSON_HIGH_CONFIDENCE_DISTANCE,
    CONF_PERSON_MEDIUM_CONFIDENCE_DISTANCE,
    DEFAULT_HIGH_CONFIDENCE_DISTANCE,
    DEFAULT_MEDIUM_CONFIDENCE_DISTANCE,
    UPDATE_INTERVAL,
    ENTRY_TYPE_ROOM,
    CONF_ENTRY_TYPE,
    CONF_AREA_ID,
    CONF_SCANNER_AREAS,
    STATE_OCCUPIED,
    CONF_PERSON_DECAY_TIMEOUT,
    DEFAULT_PERSON_DECAY_TIMEOUT,
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_STALE,
    TRACKING_STATUS_LOST,
    STALE_THRESHOLD_SECONDS,
    MAX_RECENT_PATH_LENGTH,
    # PATH-ALPHA D2a (rev-3.5.1): unified matrix classifier vocabulary + knob.
    TRACKING_REASON_VALUES,
    BLE_SILENT_ONLY_AWAY_CONFIDENCE,
    ATTR_TRACKING_REASON,
    ATTR_TRACKER_SOURCES,
)

# PATH-ALPHA D2a: BLE fleet liveness window (seconds). If any tracked
# person had a Bermuda area update within this window, the scanner fleet
# is considered "provably live" and a per-person BLE=silent stamp is
# admissible as row 14 (away_ble_silent_only). Otherwise BLE=silent
# degrades to BLE=indeterminate and the person falls to row 16 (no_signal)
# rather than casting a spurious away vote. Rung 1 (module constant) —
# protocol-level fail-safe; any change requires code review.
BLE_FLEET_LIVENESS_WINDOW_S = 90

_LOGGER = logging.getLogger(__name__)


# PATH-ALPHA D2a: matrix-row stamp builder. Enforces WARN-gated vocabulary
# — any tracking_reason not in TRACKING_REASON_VALUES logs a WARN and is
# preserved as-is (fail-open so a typo doesn't silently disappear a
# person; tests assert the frozenset invariant separately).
def _stamp(status: str, location: str, confidence: float,
           tracking_reason: str, tracker_sources: dict[str, str]) -> dict[str, Any]:
    if tracking_reason not in TRACKING_REASON_VALUES:
        _LOGGER.warning(
            "PATH-ALPHA classifier: tracking_reason=%r not in TRACKING_REASON_VALUES "
            "(vocabulary drift — fix classifier or const.py)", tracking_reason,
        )
    return {
        "tracking_status": status,
        "location": location,
        "confidence": confidence,
        ATTR_TRACKING_REASON: tracking_reason,
        ATTR_TRACKER_SOURCES: dict(tracker_sources),
    }


class PersonTrackingCoordinator(DataUpdateCoordinator):
    """Coordinator for person tracking across rooms."""

    def __init__(self, hass: HomeAssistant, integration_entry: ConfigEntry) -> None:
        """Initialize the person tracking coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Person Tracking",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.integration_entry = integration_entry
        self.tracked_persons = integration_entry.data.get(CONF_TRACKED_PERSONS, [])
        
        # Distance thresholds for confidence calculation
        self.high_confidence_distance = integration_entry.data.get(
            CONF_PERSON_HIGH_CONFIDENCE_DISTANCE,
            DEFAULT_HIGH_CONFIDENCE_DISTANCE
        )
        self.medium_confidence_distance = integration_entry.data.get(
            CONF_PERSON_MEDIUM_CONFIDENCE_DISTANCE,
            DEFAULT_MEDIUM_CONFIDENCE_DISTANCE
        )
        
        # v3.2.4: Scanner-to-rooms mapping for three-tier resolution
        self._scanner_to_rooms: dict[str, list[str]] = {}
        self._area_id_to_room: dict[str, str] = {}  # area_id -> room_name (direct match)
        self._room_coordinators: dict[str, Any] = {}  # room_name -> coordinator reference
        # v3.8.9: Rooms with direct (Tier 1) BLE coverage (no CONF_SCANNER_AREAS)
        self._direct_ble_rooms: set[str] = set()
        # v3.6.21: Cache scanner map — only rebuild when room entries change
        self._scanner_map_entry_ids: set[str] = set()
        
        # v3.2.8.1: Decay timeout for staleness detection
        self.decay_timeout = integration_entry.data.get(
            CONF_PERSON_DECAY_TIMEOUT,
            DEFAULT_PERSON_DECAY_TIMEOUT
        )
        
        # D6+D7: DB visit tracking for person entry/exit/snapshot logging
        self._active_visit_ids: dict[str, int] = {}  # person_name -> visit_id
        # v4.2.6: Defer first snapshot to reduce startup DB contention
        self._last_snapshot_time: datetime = dt_util.now()
        self._SNAPSHOT_INTERVAL_SECONDS = 900  # 15 minutes

        # v3.18.6: BLE pre-arrival detection state
        self._person_was_away: dict[str, bool] = {}
        self._person_lost_since: dict[str, datetime] = {}  # When person went LOST
        # v5.7.0 fix-up FIX-5 (MED-B1): WS-A grace MUST NOT shift the timing
        # of the BLE pre-arrival feature (which reads `_person_lost_since`
        # with its own `_min_away_minutes` budget). Keep a SEPARATE stamp
        # dict for the WS-A2 path-β grace; it is populated at the SAME LOST
        # sites and cleared at the SAME home transitions, but lives apart so
        # BLE pre-arrival semantics are byte-unaffected.
        self._lost_away_since: dict[str, datetime] = {}
        self._pre_arrival_enabled: bool = True
        self._min_away_minutes: int = 15  # Minimum LOST time before BLE re-detection triggers pre-arrival

        _LOGGER.info(
            "Person tracking coordinator initialized for %d persons: %s (decay timeout: %ds)",
            len(self.tracked_persons),
            self.tracked_persons,
            self.decay_timeout
        )

        # PATH-ALPHA D2a: one-time-per-boot NM note guard for missing person
        # entities (S6 pre-matrix guard). A persistent config error must not
        # spam NM every tick; the set is cleared only on process restart.
        self._entity_missing_noted: set[str] = set()

    # =========================================================================
    # PATH-ALPHA D2a (rev-3.5.1) — UNIFIED MATRIX CLASSIFIER
    # =========================================================================
    # HISTORICAL LINEAGE: this classifier corrects v4.7.14.1 H3 / Gap C's
    # over-reach — that hotfix rightly distrusted stale-fallback locations
    # but lumped confidently-away trackers in with genuinely-unknown ones
    # under a single LOST label, silently emptying the trusted denominator
    # in AWAY-BLOCK-1 three months later. The rev-3.5.1 unified matrix
    # PRESERVES H3's correct half (row 16 no_signal fail-safe + the
    # `tracked_count > 0` guard consumed at presence.py) while decomposing
    # the over-reach: positive-away-evidence tuples now stamp ACTIVE+away
    # via `tracking_reason` (rows 6/9/11/13/14), and BLE-silent-at-home
    # with a non-BLE home affirmation stamps ACTIVE+home+`home_ble_silent`
    # (rows 2/3/5/10) instead of vanishing into LOST. TRUE LOST is
    # reserved for S5 (`no_signal`, row 16) and S6 (`entity_missing`,
    # pre-matrix guard). MUST NOT be widened back — see
    # docs/planning/AUDIT_tracking_status_consumers.md §historical lineage.
    #
    # INVARIANT I-α (falsifiable): no-signal MUST NEVER produce an away
    # vote. Any classifier output whose (state, location) pair implies a
    # trusted-away contribution and whose tracking_reason is `no_signal`
    # violates the invariant.
    # =========================================================================

    def _read_source_inventory(self, person_state) -> dict[str, str]:
        """Live per-tick source-axis inventory for one person.

        Returns a dict keyed by axis ('gps', 'wifi', 'ble') with vocabulary
        values drawn from rev-3.5.1: GPS ∈ {home, away, unknown, MISSING};
        WiFi ∈ {home, not_home, unavailable, MISSING}; BLE ∈ {visible,
        silent, indeterminate, MISSING}. Never cached — this is called on
        every classifier invocation so a person that gains or loses a
        tracker mid-day is reflected immediately (operator: "GPS presence
        is mutable for now").

        BLE axis is intentionally left at MISSING here; the caller layers
        Bermuda-area-sensor evidence + fleet-liveness on top.
        """
        sources: dict[str, str] = {"gps": "MISSING", "wifi": "MISSING", "ble": "MISSING"}
        try:
            attrs = getattr(person_state, "attributes", {}) or {}
            device_trackers = attrs.get("device_trackers") or []
        except Exception:  # noqa: BLE001 - defensive
            return sources

        for tracker_id in device_trackers:
            try:
                ts = self.hass.states.get(tracker_id)
            except Exception:  # noqa: BLE001
                continue
            if ts is None:
                continue
            try:
                t_attrs = getattr(ts, "attributes", {}) or {}
                src_type = str(t_attrs.get("source_type", "")).lower()
                state = str(getattr(ts, "state", "") or "")
            except Exception:  # noqa: BLE001
                continue

            if src_type == "gps":
                # HA companion GPS: state in {"home","not_home","<zone>","unknown","unavailable"}.
                if state == "home":
                    sources["gps"] = "home"
                elif state in ("unknown", "unavailable", "", "None"):
                    sources["gps"] = "unknown"
                else:
                    # not_home OR any named zone → treat as away signal.
                    sources["gps"] = "away"
            elif src_type == "router":
                if state == "home":
                    sources["wifi"] = "home"
                elif state in ("unavailable",):
                    sources["wifi"] = "unavailable"
                elif state in ("unknown", "", "None"):
                    sources["wifi"] = "unavailable"
                else:
                    sources["wifi"] = "not_home"
            # BLE trackers show up as source_type=bluetooth_le / private_ble;
            # handled via the Bermuda area sensor path (higher-fidelity than
            # the raw device_tracker.state).
        return sources

    def _ble_fleet_live(self, now: datetime) -> bool:
        """True if the BLE scanner fleet is provably live in the last window.

        Uses the PREVIOUS-tick `self.data` snapshot: if any tracked person
        has a `last_bermuda_update` within BLE_FLEET_LIVENESS_WINDOW_S, the
        fleet is currently detecting *someone*, so a per-person BLE=silent
        stamp is admissible as row 14 (away_ble_silent_only). Otherwise
        BLE=silent degrades to indeterminate and the person falls to
        row 16 (no_signal) rather than casting a spurious away vote.

        A-M1 fix (2026-08-16): empty `self.data` is the FIRST-TICK
        boot state — there is no evidence YET that the fleet is live.
        Prior behavior returned True (fail-open) which admitted
        `away_ble_silent_only` stamps during the boot-window with
        conf 0.82; the outer wrapper's `_ps_state=="not_home"`
        coercion neutralized the vote-shape risk (I-α still held), but
        `tracking_reason` was mis-attributed to BLE-only-away instead
        of the true `away_wifi_only` shape. Now returns False on
        empty data: no boot-tick BLE-only admission until at least
        one Bermuda update proves the fleet responsive. I-α is
        UNCHANGED (still no away vote from zero evidence — the row-16
        fallback still fires; the wrapper still coerces
        `_ps_state=="not_home"` to away via `away_wifi_only`). See
        Review A M1.

        Fail-open on `.data` access exception preserved (attribute
        error path); the fix targets the deterministic empty case.
        """
        try:
            data = self.data or {}
        except Exception:  # noqa: BLE001
            return True  # exception path: fail-open (unchanged)
        if not data:
            return False  # A-M1: first-tick / boot — fleet not proven live
        window = timedelta(seconds=BLE_FLEET_LIVENESS_WINDOW_S)
        for _pname, pinfo in data.items():
            last = pinfo.get("last_bermuda_update") if isinstance(pinfo, dict) else None
            if last is None:
                continue
            try:
                if (now - last) <= window:
                    return True
            except Exception:  # noqa: BLE001 - tz-aware vs naive
                continue
        return False

    def _classify_matrix_row(
        self,
        person_hass_state: str,
        sources: dict[str, str],
        ble_axis: str,
        ble_liveness_provable: bool,
    ) -> dict[str, Any]:
        """Map (person_state, GPS, WiFi, BLE) tuple → matrix row stamp.

        Returns a dict with keys: tracking_status, location, confidence,
        tracking_reason, tracker_sources. Called from the two "Bermuda
        exists but no room" and "no Bermuda sensor" branches; row 1
        (BLE-visible@home_room) is handled inline at the room-resolved
        branch since it already has the room name in hand.

        INVARIANT I-α enforced here: `no_signal` NEVER pairs with an
        away location. Rows 4/8 (S4 anomalous) are still stamped ACTIVE
        per rev-3.5.1 with a distinct `tracking_reason` — H3's away-block
        pathology came from *silent* LOST-inclusion, not from labeled
        deferral.
        """
        gps = sources.get("gps", "MISSING")
        wifi = sources.get("wifi", "MISSING")
        ble = ble_axis if ble_axis in ("visible", "silent", "indeterminate", "MISSING") else "MISSING"
        # Liveness gate: BLE=silent requires provable fleet liveness. Else
        # degrade to indeterminate (contributes no positive evidence).
        if ble == "silent" and not ble_liveness_provable:
            ble = "indeterminate"

        state_str = (person_hass_state or "").lower()
        sources_out = {"gps": gps, "wifi": wifi, "ble": ble}

        gps_home = gps == "home"
        gps_away = gps == "away"
        wifi_home = wifi == "home"
        wifi_not_home = wifi == "not_home"

        # ---- S2 case-(b): affirmative non-BLE home evidence. Rows 2/3/10 ----
        if gps_home and wifi_home:
            conf = 0.85 if ble == "silent" else 0.80  # row 2 vs row 3
            return _stamp(TRACKING_STATUS_ACTIVE, "home", conf, "home_ble_silent", sources_out)
        if gps_home and wifi == "not_home":
            # Row 4 anomaly (GPS home + WiFi off): still ACTIVE-home, low
            # conf; instrumentation via `anomalous_gps_stale_local_gone`.
            return _stamp(TRACKING_STATUS_ACTIVE, "home", 0.5,
                          "anomalous_gps_stale_local_gone", sources_out)
        if gps_home and wifi in ("unavailable", "MISSING"):
            # Row 10 case-(b) GPS-only home.
            return _stamp(TRACKING_STATUS_ACTIVE, "home", 0.75,
                          "home_ble_silent", sources_out)

        # ---- S4 anomaly: GPS-lag arrival (row 8) ----
        if gps_away and wifi_home:
            return _stamp(TRACKING_STATUS_ACTIVE, "home", 0.85,
                          "anomalous_gps_lag_arrival", sources_out)

        # ---- S3 away rows ----
        if gps_away and wifi_not_home:
            return _stamp(TRACKING_STATUS_ACTIVE, "away", 0.99,
                          "away_all_agree", sources_out)
        if gps_away and wifi in ("unavailable", "MISSING"):
            return _stamp(TRACKING_STATUS_ACTIVE, "away", 0.92,
                          "away_gps_only", sources_out)

        # GPS unknown/MISSING from here.
        # Case-(b) via WiFi-only home (operator forest-check: WiFi=home
        # alone is affirmative → S2). Row 3-equivalent when BLE cold; row
        # 2-equivalent when BLE silent w/ liveness proof.
        if wifi_home:
            conf = 0.85 if ble == "silent" else 0.75
            return _stamp(TRACKING_STATUS_ACTIVE, "home", conf,
                          "home_ble_silent", sources_out)

        if wifi_not_home and ble == "silent":
            return _stamp(TRACKING_STATUS_ACTIVE, "away", 0.95,
                          "away_wifi_silent_local", sources_out)
        if wifi_not_home:
            return _stamp(TRACKING_STATUS_ACTIVE, "away", 0.90,
                          "away_wifi_only", sources_out)

        # Row 14 — BLE-only away (Ziri canonical path). Knob-controlled;
        # default 0.82 < path-α threshold 0.9 so solo BLE-only cannot flip
        # house alone. See const.py BLE_SILENT_ONLY_AWAY_CONFIDENCE.
        if ble == "silent":
            return _stamp(TRACKING_STATUS_ACTIVE, "away",
                          BLE_SILENT_ONLY_AWAY_CONFIDENCE,
                          "away_ble_silent_only", sources_out)

        # ---- Fallback on HA person aggregation when sources are all silent ----
        # This preserves case-(b) for a person whose device_trackers list
        # is empty but HA's own aggregation reports "home" (e.g. via
        # zone-based person entity fed by a source we didn't classify).
        if state_str == "home":
            return _stamp(TRACKING_STATUS_ACTIVE, "home", 0.75,
                          "home_ble_silent", sources_out)
        # Named zone / not_home via HA aggregation → treat as WiFi-only away
        # equivalent (rev-3.5.1 §3 :385 disposition).
        if state_str and state_str not in ("unknown", "unavailable", "none"):
            if state_str == "not_home":
                return _stamp(TRACKING_STATUS_ACTIVE, "away", 0.90,
                              "away_wifi_only", sources_out)
            # Named zone → still an away-affirmative HA state.
            return _stamp(TRACKING_STATUS_ACTIVE, "away", 0.90,
                          "away_wifi_only", sources_out)

        # ---- S5 row 16 — NO_SIGNAL / epistemic null. INVARIANT I-α: no
        #      away vote from this cell. Refuses to vote. Fail-safe. ----
        return _stamp(TRACKING_STATUS_LOST, "unknown", 0.0,
                      "no_signal", sources_out)

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Fetch person location data with staleness decay tracking.
        
        v3.2.8.1: Implements presence decay logic that was missing from v3.2.8:
        - Tracks last_bermuda_update timestamp
        - Calculates tracking_status (active/stale/lost)
        - Maintains previous_location_time for Previous Seen sensor
        - Builds recent_path for debugging movement patterns
        """
        try:
            # v3.2.4: Build scanner-to-room mapping on each update
            await self._build_scanner_room_map()
            
            person_data = {}
            now = dt_util.now()
            
            for person_name in self.tracked_persons:
                # Get old data before update
                old_data = self.data.get(person_name, {}) if self.data else {}
                old_location = old_data.get("location", "unknown")
                old_path = old_data.get("recent_path", [])
                old_previous_location_time = old_data.get("previous_location_time")
                old_last_bermuda_update = old_data.get("last_bermuda_update")
                
                # Get person entity
                person_entity_id = f"person.{person_name.lower().replace(' ', '_')}"
                person_state = self.hass.states.get(person_entity_id)
                
                if not person_state:
                    # PATH-ALPHA D2a rev-3.5.1 PRE-MATRIX GUARD (S6):
                    # `person.<name>` entity does not exist — a persistent
                    # config error, structurally distinct from S5 no_signal
                    # (which is transient). One-time WARN per boot to avoid
                    # NM spam; NM wiring is a separate deliverable.
                    if person_name not in self._entity_missing_noted:
                        _LOGGER.warning(
                            "Person entity not found: %s (S6 entity_missing "
                            "pre-matrix guard — persistent config error; "
                            "person will be excluded from I-α denominator)",
                            person_entity_id,
                        )
                        self._entity_missing_noted.add(person_name)
                    # v5.7.0 WS-A3: stamp LOST-since for grace timing.
                    if person_name not in self._person_lost_since:
                        self._person_lost_since[person_name] = now
                    # v5.7.0 fix-up FIX-5: parallel stamp on the WS-A-only
                    # map. Separate from `_person_lost_since` so BLE
                    # pre-arrival timing is unaffected.
                    if person_name not in self._lost_away_since:
                        self._lost_away_since[person_name] = now
                    person_data[person_name] = {
                        "location": "unknown",
                        "previous_location": old_location,
                        "previous_location_time": old_previous_location_time,
                        "last_changed": None,
                        "last_bermuda_update": None,
                        "tracking_status": TRACKING_STATUS_LOST,
                        "confidence": 0.0,
                        "method": "none",
                        "recent_path": old_path,
                        # PATH-ALPHA D2a: S6 attributes.
                        ATTR_TRACKING_REASON: "entity_missing",
                        ATTR_TRACKER_SOURCES: {"gps": "MISSING", "wifi": "MISSING", "ble": "MISSING"},
                    }
                    continue
                
                # Get Bermuda area sensor for room-level location
                area_sensor = await self._find_bermuda_area_sensor(person_name)
                
                if area_sensor:
                    area_state = self.hass.states.get(area_sensor)
                    if area_state and area_state.state not in ("unknown", "unavailable"):
                        # v3.2.4: Resolve Bermuda area to actual room using three-tier strategy
                        bermuda_area = area_state.state
                        resolved_room = self._resolve_person_room(bermuda_area)
                        
                        # Calculate confidence based on Bermuda distance sensors
                        confidence = await self._calculate_confidence(person_name, bermuda_area, resolved_room)
                        
                        # v3.2.8.3: Track location changes and previous_location_time
                        location_changed = (resolved_room != old_location)
                        previous_location_time = old_previous_location_time
                        if location_changed and old_location not in ("unknown", ""):
                            # v3.2.8.3 FIX: Record NOW (when person left), not old last_changed (when they entered)
                            previous_location_time = now
                            _LOGGER.debug(
                                "Person %s moved: '%s' -> '%s' (previous seen: %s)",
                                person_name, old_location, resolved_room, previous_location_time
                            )

                            # v3.3.0: Fire location change event for transition detection
                            event_data = {
                                "person_id": person_name,
                                "previous_location": old_location,
                                "current_location": resolved_room,
                                "timestamp": now
                            }
                            self.hass.bus.async_fire(
                                "ura_person_location_change",
                                event_data
                            )
                            _LOGGER.debug(
                                "Fired ura_person_location_change event: %s",
                                event_data
                            )

                            # D6: Log person exit (old room) and entry (new room) to database
                            self.hass.async_create_task(
                                self._log_person_room_change(
                                    person_name, old_location, resolved_room,
                                    confidence, "bermuda",
                                )
                            )
                        
                        # v3.2.8.1: Track recent path
                        recent_path = self._update_recent_path(old_path, resolved_room, old_location)
                        
                        # v3.2.8.1: Bermuda update detected - mark as active
                        last_bermuda_update = now
                        tracking_status = TRACKING_STATUS_ACTIVE
                        
                        # PATH-ALPHA D2a rev-3.5.1: S1 row 1 — BLE visible at
                        # a home room (Bermuda-authoritative). Attach live
                        # source inventory (BLE axis = visible@<home_room>).
                        _s1_sources = self._read_source_inventory(person_state)
                        _s1_sources["ble"] = "visible"
                        person_data[person_name] = {
                            "location": resolved_room,
                            "bermuda_area": bermuda_area,  # Original Bermuda area for debugging
                            "previous_location": old_location,
                            "previous_location_time": previous_location_time,
                            "last_changed": area_state.last_changed,
                            "last_bermuda_update": last_bermuda_update,
                            "tracking_status": tracking_status,
                            "confidence": confidence,
                            "method": "bermuda",
                            "recent_path": recent_path,
                            # PATH-ALPHA D2a: S1 attributes (row 1).
                            ATTR_TRACKING_REASON: "bermuda",
                            ATTR_TRACKER_SOURCES: _s1_sources,
                        }
                        
                        _LOGGER.debug(
                            "Person %s: Bermuda area '%s' resolved to room '%s' (confidence: %.2f, status: %s)",
                            person_name, bermuda_area, resolved_room, confidence, tracking_status
                        )

                        # v3.18.6: Detect BLE away→present transition for pre-arrival
                        # Guard: only trigger if person was LOST for >= min_away_minutes
                        # This prevents false triggers from quick trips (gardening, mailbox, etc.)
                        was_away = self._person_was_away.get(person_name, False)
                        if resolved_room and was_away:
                            # Person just appeared via BLE after being genuinely away
                            self._person_was_away[person_name] = False
                            self._person_lost_since.pop(person_name, None)
                            # v5.7.0 fix-up FIX-5: parallel clear.
                            self._lost_away_since.pop(person_name, None)
                            if self._pre_arrival_enabled:
                                # v3.21.1: Check Presence observation mode before dispatching
                                # DOMAIN already imported at module level (line 32)
                                mgr = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
                                presence_obs = False
                                if mgr:
                                    pres = getattr(mgr, "coordinators", {}).get("presence")
                                    if pres:
                                        presence_obs = getattr(pres, "observation_mode", False)
                                if presence_obs:
                                    _LOGGER.info(
                                        "BLE pre-arrival: %s [observation mode] would dispatch SIGNAL_PERSON_ARRIVING",
                                        person_name,
                                    )
                                else:
                                    from homeassistant.helpers.dispatcher import async_dispatcher_send
                                    from .domain_coordinators.signals import SIGNAL_PERSON_ARRIVING
                                    person_entity = self._find_person_entity(person_name)
                                    if person_entity:
                                        async_dispatcher_send(
                                            self.hass,
                                            SIGNAL_PERSON_ARRIVING,
                                            {"person_entity": person_entity, "source": "ble"},
                                        )
                                    _LOGGER.info(
                                        "BLE pre-arrival: %s detected in %s (was away >%dm)",
                                        person_name, resolved_room, self._min_away_minutes,
                                    )
                        elif resolved_room:
                            # Present — clear away state
                            self._person_was_away[person_name] = False
                            self._person_lost_since.pop(person_name, None)
                            # v5.7.0 fix-up FIX-5: parallel clear.
                            self._lost_away_since.pop(person_name, None)
                        else:
                            # No room detected — track LOST duration
                            if tracking_status == TRACKING_STATUS_LOST:
                                if person_name not in self._person_lost_since:
                                    self._person_lost_since[person_name] = now
                                # v5.7.0 fix-up FIX-5: parallel stamp. Note
                                # this branch is BLE-LOST without a person
                                # away/home opinion — we still stamp the
                                # WS-A map; the WS-A2 denominator gates
                                # further (LOST+away required).
                                if person_name not in self._lost_away_since:
                                    self._lost_away_since[person_name] = now
                                lost_duration = (now - self._person_lost_since[person_name]).total_seconds()
                                if lost_duration >= self._min_away_minutes * 60:
                                    self._person_was_away[person_name] = True
                    else:
                        # Bermuda sensor exists but no room detected
                        # v3.2.8.1: Check if we have recent Bermuda data to decay
                        if old_last_bermuda_update:
                            time_since_update = (now - old_last_bermuda_update).total_seconds()
                            if time_since_update < self.decay_timeout:
                                # Still within decay window - keep old location but mark as stale
                                tracking_status = TRACKING_STATUS_STALE
                                location = old_location
                                last_bermuda_update = old_last_bermuda_update
                                confidence = max(0.1, old_data.get("confidence", 0.3) * 0.5)  # Decay confidence
                                
                                # PATH-ALPHA D2a: O2 STALE overlay — inherit
                                # tracking_reason from the last active stamp
                                # (rev-3.5.1 §3 :314 disposition).
                                person_data[person_name] = {
                                    "location": location,
                                    "previous_location": old_data.get("previous_location", "unknown"),
                                    "previous_location_time": old_previous_location_time,
                                    "last_changed": old_data.get("last_changed"),
                                    "last_bermuda_update": last_bermuda_update,
                                    "tracking_status": tracking_status,
                                    "confidence": confidence,
                                    "method": "bermuda_decay",
                                    "recent_path": old_path,
                                    ATTR_TRACKING_REASON: old_data.get(ATTR_TRACKING_REASON, "bermuda"),
                                    ATTR_TRACKER_SOURCES: old_data.get(
                                        ATTR_TRACKER_SOURCES,
                                        {"gps": "MISSING", "wifi": "MISSING", "ble": "indeterminate"},
                                    ),
                                }
                                _LOGGER.debug(
                                    "Person %s: Bermuda stale (%.0fs since update), keeping location '%s' with status '%s'",
                                    person_name, time_since_update, location, tracking_status
                                )
                                continue
                        
                        # No recent Bermuda data or exceeded decay timeout - check person state for home/away
                        # v4.2.27: preserve previous_location/_time across already-away (or already-home)
                        # cycles. Capture transition only when old_location is a real room. Earlier
                        # logic clobbered both fields after one steady-state cycle, leaving
                        # previous_seen=unknown for anyone away >1 update interval.
                        old_previous_location = old_data.get("previous_location", "unknown")
                        was_real_room = old_location and old_location not in ("away", "home", "unknown", "")
                        if was_real_room:
                            # Real room → away/home transition: capture
                            new_previous_location = old_location
                            new_previous_location_time = now
                        else:
                            # Already in state-string territory: preserve real-room history
                            new_previous_location = old_previous_location
                            new_previous_location_time = old_previous_location_time

                        # PATH-ALPHA D2a rev-3.5.1: Bermuda sensor exists but
                        # NO room resolved. Three-way positive-evidence split
                        # replacing the prior two-way (home vs else) branch
                        # that stamped LOST for BOTH ACTIVE-home (case-b) AND
                        # ACTIVE-away — the v4.7.14.1 H3 over-reach that
                        # emptied the trusted denominator (AWAY-BLOCK-1).
                        #
                        # Precedence: `home` → S2 (ACTIVE-home, home_ble_silent
                        # or matrix-derived); `not_home`/named-zone → S3 (ACTIVE
                        # -away with per-source reason); `unknown`/`unavailable`
                        # /None → S5 LOST + `no_signal`, EXCLUDED from I-α.
                        # NO-SIGNAL MUST NEVER PRODUCE AN AWAY VOTE (I-α).
                        _ps_state = (person_state.state or "").lower()
                        _sources = self._read_source_inventory(person_state)
                        _ble_live = self._ble_fleet_live(now)
                        # BLE axis = silent (bermuda area sensor is unresolved
                        # this tick, so we've *tried* to see BLE and got
                        # nothing) — liveness gate decides silent vs indeterminate.
                        _stamp_row = self._classify_matrix_row(
                            _ps_state, _sources, "silent", _ble_live,
                        )
                        if _ps_state == "home":
                            # S2 case-(b): NEVER LOST. Force location=home even
                            # if source-derivation was inconclusive (HA person
                            # aggregation is our authority for "home"). Case-(b)
                            # never-collapses-to-LOST pin (rev-3.5.1).
                            _stamp_row["tracking_status"] = TRACKING_STATUS_ACTIVE
                            _stamp_row["location"] = "home"
                            if _stamp_row.get(ATTR_TRACKING_REASON) not in (
                                # C-HIGH-2 (2026-08-16): removed the
                                # `anomalous_wifi_gone_local_home` entry
                                # from this whitelist — the value was
                                # dead vocabulary (no emission site) and
                                # is retired from TRACKING_REASON_VALUES.
                                # Row 5 is intercepted by the Bermuda-
                                # authoritative branch upstream and
                                # never reaches this code with that
                                # reason.
                                "home_ble_silent",
                                "anomalous_gps_lag_arrival",
                                "anomalous_gps_stale_local_gone",
                            ):
                                _stamp_row[ATTR_TRACKING_REASON] = "home_ble_silent"
                            if _stamp_row.get("confidence", 0.0) < 0.3:
                                _stamp_row["confidence"] = 0.75
                            # v5.7.0 WS-A3: LOST-home is NOT path-β eligible —
                            # case-(b) is ACTIVE-home; clear grace stamps.
                            self._person_lost_since.pop(person_name, None)
                            self._lost_away_since.pop(person_name, None)
                        elif _ps_state in ("unknown", "unavailable", "", "none"):
                            # S5 row 16 — NO_SIGNAL fail-safe. LOST + no vote.
                            # Preserves H3's correct half (no away vote from
                            # zero evidence). MUST NOT be widened to include
                            # confidently-away — that was the H3 over-reach.
                            _stamp_row["tracking_status"] = TRACKING_STATUS_LOST
                            _stamp_row["location"] = "unknown"
                            _stamp_row[ATTR_TRACKING_REASON] = "no_signal"
                            _stamp_row["confidence"] = 0.0
                            if person_name not in self._person_lost_since:
                                self._person_lost_since[person_name] = now
                            if person_name not in self._lost_away_since:
                                self._lost_away_since[person_name] = now
                            # DO NOT set _person_was_away — no away evidence.
                        else:
                            # S3 case-(a): ACTIVE + away with matrix-derived
                            # tracking_reason. Formerly stamped LOST → AWAY-
                            # BLOCK-1 root cause. Preserve `_person_was_away`.
                            _stamp_row["tracking_status"] = TRACKING_STATUS_ACTIVE
                            _stamp_row["location"] = "away"
                            if _stamp_row.get(ATTR_TRACKING_REASON) == "no_signal":
                                _stamp_row[ATTR_TRACKING_REASON] = "away_wifi_only"
                                _stamp_row["confidence"] = 0.9
                            if person_name not in self._person_lost_since:
                                self._person_lost_since[person_name] = now
                            if person_name not in self._lost_away_since:
                                self._lost_away_since[person_name] = now
                            # PRESERVE (Review M3, AUDIT §3 :385/:428): case-(a)
                            # away must set _person_was_away so BLE pre-arrival
                            # fires on the next home-visible tick.
                            self._person_was_away[person_name] = True

                        person_data[person_name] = {
                            "location": _stamp_row["location"],
                            "previous_location": new_previous_location,
                            "previous_location_time": new_previous_location_time,
                            "last_changed": person_state.last_changed,
                            "last_bermuda_update": None,
                            "tracking_status": _stamp_row["tracking_status"],
                            "confidence": _stamp_row["confidence"],
                            "method": "person_state",
                            "recent_path": [],
                            ATTR_TRACKING_REASON: _stamp_row[ATTR_TRACKING_REASON],
                            ATTR_TRACKER_SOURCES: _stamp_row[ATTR_TRACKER_SOURCES],
                        }
                else:
                    # PATH-ALPHA D2a rev-3.5.1: NO Bermuda sensor at all.
                    # Same three-way split as the "Bermuda-but-no-room" branch
                    # (rev-3.5.1 §3 :428 disposition). Prior code stamped LOST
                    # for both home and away → identical H3 over-reach root
                    # cause. Now: home→S2 row 10 (home_ble_silent), not_home/
                    # named→S3 (per-source reason), unknown→S5 no_signal.
                    _ps_state = (person_state.state or "").lower()
                    _sources = self._read_source_inventory(person_state)
                    _ble_live = self._ble_fleet_live(now)
                    # BLE axis = MISSING (no Bermuda sensor configured at all).
                    _stamp_row = self._classify_matrix_row(
                        _ps_state, _sources, "MISSING", _ble_live,
                    )

                    # v4.2.27: same preservation logic as the no-Bermuda-area branch above
                    old_previous_location = old_data.get("previous_location", "unknown")
                    was_real_room = old_location and old_location not in ("away", "home", "unknown", "")
                    if was_real_room:
                        new_previous_location = old_location
                        new_previous_location_time = now
                    else:
                        new_previous_location = old_previous_location
                        new_previous_location_time = old_previous_location_time

                    if _ps_state == "home":
                        # S2 case-(b) row 10 — NEVER LOST (rev-3.5.1 pin).
                        _stamp_row["tracking_status"] = TRACKING_STATUS_ACTIVE
                        _stamp_row["location"] = "home"
                        if _stamp_row.get(ATTR_TRACKING_REASON) not in (
                            # C-HIGH-2 (2026-08-16): retired
                            # `anomalous_wifi_gone_local_home` — dead
                            # vocab, folded into Bermuda-authoritative
                            # interception upstream.
                            "home_ble_silent",
                            "anomalous_gps_lag_arrival",
                            "anomalous_gps_stale_local_gone",
                        ):
                            _stamp_row[ATTR_TRACKING_REASON] = "home_ble_silent"
                        if _stamp_row.get("confidence", 0.0) < 0.3:
                            _stamp_row["confidence"] = 0.75
                        self._person_lost_since.pop(person_name, None)
                        self._lost_away_since.pop(person_name, None)
                    elif _ps_state in ("unknown", "unavailable", "", "none"):
                        # S5 row 16 no_signal — no away vote (INVARIANT I-α).
                        _stamp_row["tracking_status"] = TRACKING_STATUS_LOST
                        _stamp_row["location"] = "unknown"
                        _stamp_row[ATTR_TRACKING_REASON] = "no_signal"
                        _stamp_row["confidence"] = 0.0
                        if person_name not in self._person_lost_since:
                            self._person_lost_since[person_name] = now
                        if person_name not in self._lost_away_since:
                            self._lost_away_since[person_name] = now
                        # DO NOT set _person_was_away.
                    else:
                        # S3 case-(a) — ACTIVE-away with per-source reason.
                        _stamp_row["tracking_status"] = TRACKING_STATUS_ACTIVE
                        _stamp_row["location"] = "away"
                        if _stamp_row.get(ATTR_TRACKING_REASON) == "no_signal":
                            _stamp_row[ATTR_TRACKING_REASON] = "away_wifi_only"
                            _stamp_row["confidence"] = 0.9
                        if person_name not in self._person_lost_since:
                            self._person_lost_since[person_name] = now
                        if person_name not in self._lost_away_since:
                            self._lost_away_since[person_name] = now
                        # PRESERVE (Review M3): case-(a) away sets was_away.
                        self._person_was_away[person_name] = True

                    person_data[person_name] = {
                        "location": _stamp_row["location"],
                        "previous_location": new_previous_location,
                        "previous_location_time": new_previous_location_time,
                        "last_changed": person_state.last_changed,
                        "last_bermuda_update": None,
                        "tracking_status": _stamp_row["tracking_status"],
                        "confidence": _stamp_row["confidence"],
                        "method": "person_state",
                        "recent_path": [],
                        ATTR_TRACKING_REASON: _stamp_row[ATTR_TRACKING_REASON],
                        ATTR_TRACKER_SOURCES: _stamp_row[ATTR_TRACKER_SOURCES],
                    }

            # D7: Periodic person snapshot logging (~every 15 minutes)
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is not None:
                should_snapshot = (
                    self._last_snapshot_time is None
                    or (now - self._last_snapshot_time).total_seconds()
                    >= self._SNAPSHOT_INTERVAL_SECONDS
                )
                if should_snapshot:
                    self._last_snapshot_time = now
                    for pname, pdata in person_data.items():
                        self.hass.async_create_task(
                            db.log_person_snapshot(
                                person_id=pname,
                                room_id=pdata.get("location"),
                                confidence=pdata.get("confidence", 0.0),
                                method=pdata.get("method", "unknown"),
                            )
                        )

            # D3 frozen-tracker check DELETED 2026-08-10 — structurally
            # unreachable (threshold 2.0d vs max HA uptime ~1d at deploy
            # cadence). See const.py FROZEN_TRACKER_DAYS tombstone.

            return person_data

        except Exception as err:
            _LOGGER.error("Error updating person tracking data: %s", err)
            raise UpdateFailed(f"Error updating person tracking data: {err}") from err

    # Stuck-Signal Watchdog D3 (v5.35.0) DELETED 2026-08-10 —
    # structurally unreachable: threshold 2.0d vs max HA uptime ~1d at
    # deploy cadence. See const.py FROZEN_TRACKER_DAYS tombstone.

    def _boot_settle_done(self) -> bool:
        """Return True once presence has released the shared boot-settle gate.

        Consults the same source of truth used by ActuatorReconciler
        (see actuator_reconciler.py:396) so the D3 (and defensively any
        stuck_signal emit routed via this coord) short-circuits until the
        canonical presence boot-settle predicate flips True. Fail-open on
        missing coordinator manager (returns True — do not silence D3
        forever if presence is absent).
        """
        try:
            mgr = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if mgr is None:
                return True
            presence = getattr(mgr, "coordinators", {}).get("presence")
            if presence is None:
                return True
            return bool(getattr(presence, "_boot_settle_done", True))
        except Exception:  # noqa: BLE001 - defensive
            return True


    async def _log_person_room_change(
        self,
        person_name: str,
        old_room: str,
        new_room: str,
        confidence: float,
        method: str,
    ) -> None:
        """Log person exit from old room and entry to new room in database.

        Manages active visit IDs for exit/entry pairing.
        """
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is None:
            return

        try:
            # Close the previous visit (exit old room)
            old_visit_id = self._active_visit_ids.pop(person_name, None)
            if old_visit_id is not None and old_visit_id > 0:
                await db.log_person_exit(visit_id=old_visit_id)

            # Open a new visit (enter new room) — skip for non-room locations
            if new_room not in ("away", "unknown", "home", ""):
                visit_id = await db.log_person_entry(
                    person_id=person_name,
                    room_id=new_room,
                    confidence=confidence,
                    detection_method=method,
                    transition_from=old_room,
                )
                if visit_id > 0:
                    self._active_visit_ids[person_name] = visit_id
        except Exception as e:
            _LOGGER.error("Error logging person room change for %s: %s", person_name, e)

    async def _build_scanner_room_map(self) -> None:
        """
        Build mapping from scanner area_ids to room names.

        v3.6.21: Cached — only rebuilds when room config entries change.

        This enables three-tier resolution:
        - Tier 1: Direct area match (area_id == bermuda area)
        - Tier 2: Scanner areas override (scanner_areas contains bermuda area)
        - Tier 3: Occupancy disambiguation (when multiple rooms share scanner)
        """
        # v3.6.21: Check if room entries changed since last build
        current_entry_ids = set()
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                current_entry_ids.add(entry.entry_id)

        if current_entry_ids == self._scanner_map_entry_ids and self._area_id_to_room:
            # Room coordinators may change each cycle (new coordinators init), refresh those only
            domain_data = self.hass.data.get(DOMAIN, {})
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                    continue
                room_name = entry.data.get("room_name")
                if room_name and entry.entry_id in domain_data:
                    coordinator = domain_data[entry.entry_id]
                    if hasattr(coordinator, 'data'):
                        self._room_coordinators[room_name] = coordinator
            return

        self._scanner_map_entry_ids = current_entry_ids
        self._scanner_to_rooms = {}
        self._area_id_to_room = {}
        self._room_coordinators = {}
        self._direct_ble_rooms = set()

        # Get area registry for name resolution
        area_reg = ar.async_get(self.hass)

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            
            room_name = entry.data.get("room_name")
            if not room_name:
                continue
            
            # Get config from both data and options (options override)
            config = {**entry.data, **entry.options}
            
            area_id = config.get(CONF_AREA_ID)
            scanner_areas = config.get(CONF_SCANNER_AREAS) or []

            # v3.8.9: Track rooms with direct BLE coverage (Tier 1)
            # A room is Tier 1 if it has an area_id but no scanner_areas override.
            if area_id and not scanner_areas:
                self._direct_ble_rooms.add(room_name.lower().replace(" ", "_"))

            # Build area_id to room mapping for Tier 1 (direct match)
            if area_id:
                # Get the HA area name for this area_id
                area_entry = area_reg.async_get_area(area_id)
                if area_entry:
                    # Store by both area_id and area name (for flexible matching)
                    self._area_id_to_room[area_id] = room_name
                    self._area_id_to_room[area_entry.name] = room_name
                    self._area_id_to_room[area_entry.name.lower().replace(" ", "_")] = room_name
                    
                    _LOGGER.debug(
                        "Tier 1 mapping: area '%s' (id: %s) -> room '%s'",
                        area_entry.name, area_id, room_name
                    )
            
            # Build scanner areas mapping for Tier 2 (override)
            # If no scanner_areas configured, use the room's own area
            effective_scanner_areas = scanner_areas if scanner_areas else ([area_id] if area_id else [])
            
            for scanner_area in effective_scanner_areas:
                if not scanner_area:
                    continue
                    
                # Normalize area for matching
                scanner_area_normalized = scanner_area.lower().replace(" ", "_")
                
                if scanner_area_normalized not in self._scanner_to_rooms:
                    self._scanner_to_rooms[scanner_area_normalized] = []
                
                if room_name not in self._scanner_to_rooms[scanner_area_normalized]:
                    self._scanner_to_rooms[scanner_area_normalized].append(room_name)
                
                # Also add by original name for flexible matching
                if scanner_area not in self._scanner_to_rooms:
                    self._scanner_to_rooms[scanner_area] = []
                if room_name not in self._scanner_to_rooms[scanner_area]:
                    self._scanner_to_rooms[scanner_area].append(room_name)
                    
                    _LOGGER.debug(
                        "Tier 2 mapping: scanner area '%s' -> room '%s'",
                        scanner_area, room_name
                    )
            
            # Store coordinator reference for Tier 3 occupancy check
            domain_data = self.hass.data.get(DOMAIN, {})
            if entry.entry_id in domain_data:
                coordinator = domain_data[entry.entry_id]
                if hasattr(coordinator, 'data'):
                    self._room_coordinators[room_name] = coordinator

    def _resolve_person_room(self, bermuda_area: str) -> str:
        """
        Resolve Bermuda scanner area to actual room name using three-tier strategy.
        
        Tier 1: Direct area match
            - If bermuda_area matches a room's CONF_AREA_ID exactly
            - Works for dense scanner homes (one scanner per room)
        
        Tier 2: Scanner areas override
            - If bermuda_area is in any room's CONF_SCANNER_AREAS list
            - Works for sparse scanner homes (shared scanners)
        
        Tier 3: Occupancy disambiguation
            - If multiple rooms claim the scanner area
            - Choose based on: currently occupied > most recently occupied > first alphabetically
        
        Args:
            bermuda_area: The area name reported by Bermuda (e.g., "Kitchen", "Study A Closet")
        
        Returns:
            The resolved room name, or bermuda_area as fallback
        """
        if not bermuda_area:
            return "unknown"
        
        bermuda_normalized = bermuda_area.lower().replace(" ", "_")
        
        # Tier 1: Direct area match
        if bermuda_area in self._area_id_to_room:
            room = self._area_id_to_room[bermuda_area]
            _LOGGER.debug("Tier 1 match: '%s' -> '%s'", bermuda_area, room)
            return room
        if bermuda_normalized in self._area_id_to_room:
            room = self._area_id_to_room[bermuda_normalized]
            _LOGGER.debug("Tier 1 match (normalized): '%s' -> '%s'", bermuda_area, room)
            return room
        
        # Tier 2: Scanner areas lookup
        candidates = []
        if bermuda_area in self._scanner_to_rooms:
            candidates = self._scanner_to_rooms[bermuda_area]
        elif bermuda_normalized in self._scanner_to_rooms:
            candidates = self._scanner_to_rooms[bermuda_normalized]
        
        if len(candidates) == 0:
            # No mapping found - return bermuda area as fallback
            _LOGGER.debug("No mapping for '%s', using as-is", bermuda_area)
            return bermuda_area
        
        if len(candidates) == 1:
            room = candidates[0]
            _LOGGER.debug("Tier 2 match (single): '%s' -> '%s'", bermuda_area, room)
            return room
        
        # Tier 3: Multiple rooms claim this scanner - disambiguate by occupancy
        _LOGGER.debug(
            "Tier 3 disambiguation needed: '%s' claimed by %s",
            bermuda_area, candidates
        )
        
        return self._disambiguate_by_occupancy(candidates, bermuda_area)

    def _disambiguate_by_occupancy(self, candidates: list[str], bermuda_area: str) -> str:
        """
        Disambiguate between multiple rooms that share a scanner.
        
        Priority:
        1. Currently occupied room (most recently became occupied wins ties)
        2. If none occupied, return first alphabetically
        
        Args:
            candidates: List of room names that claim this scanner area
            bermuda_area: Original Bermuda area for fallback
        
        Returns:
            Selected room name
        """
        occupied_rooms = []
        
        for room_name in candidates:
            if self._is_room_occupied(room_name):
                occupied_time = self._get_room_occupied_time(room_name)
                occupied_rooms.append((room_name, occupied_time))
        
        if len(occupied_rooms) == 1:
            room = occupied_rooms[0][0]
            _LOGGER.debug("Tier 3: Single occupied room '%s'", room)
            return room
        
        if len(occupied_rooms) > 1:
            # Multiple rooms occupied - pick most recently became occupied
            # Sort by time descending (most recent first), using datetime.min for None
            _epoch = dt_util.utc_from_timestamp(0)
            occupied_rooms.sort(
                key=lambda x: x[1] if x[1] else _epoch,
                reverse=True
            )
            room = occupied_rooms[0][0]
            _LOGGER.debug(
                "Tier 3: Multiple occupied, picked most recent '%s' from %s",
                room, [r[0] for r in occupied_rooms]
            )
            return room
        
        # No rooms occupied - return first alphabetically for consistency
        room = sorted(candidates)[0]
        _LOGGER.debug("Tier 3: None occupied, picked first alphabetically '%s'", room)
        return room

    def _is_room_occupied(self, room_name: str) -> bool:
        """Check if room is currently occupied via its coordinator."""
        coordinator = self._room_coordinators.get(room_name)
        if coordinator and hasattr(coordinator, 'data') and coordinator.data:
            return coordinator.data.get(STATE_OCCUPIED, False)
        return False

    def _get_room_occupied_time(self, room_name: str) -> datetime | None:
        """Get timestamp when room became occupied."""
        coordinator = self._room_coordinators.get(room_name)
        if coordinator and hasattr(coordinator, 'get_became_occupied_time'):
            return coordinator.get_became_occupied_time()
        return None

    def _find_person_entity(self, person_name: str) -> str | None:
        """Find person.* entity matching a tracked person name.

        v3.18.6: Maps BLE person name (from Bermuda sensor) to HA person entity.
        Uses the same logic as _async_update_data (line 133 pattern).
        """
        # Try direct match (same pattern as person_entity_id construction)
        candidate = f"person.{person_name.lower().replace(' ', '_')}"
        if self.hass.states.get(candidate):
            return candidate
        # Try without transformation
        candidate = f"person.{person_name}"
        if self.hass.states.get(candidate):
            return candidate
        return None

    # ==========================================================================
    # BERMUDA SENSOR DISCOVERY
    # ==========================================================================

    async def _find_bermuda_area_sensor(self, person_name: str) -> str | None:
        """Find the Bermuda area sensor for a person.

        v3.6.19: Replaced 8 hardcoded iPhone patterns with smarter discovery:
        1. Config override (CONF_BERMUDA_AREA_SENSORS per person)
        2. Private BLE derivation (device_tracker.* → sensor.*_area)
        3. Minimal fallback (2 common patterns)
        4. Registry fallback (Bermuda platform entities, last resort)
        """
        from .const import CONF_BERMUDA_AREA_SENSORS

        normalized_name = person_name.lower().replace(" ", "_")
        first_name = person_name.split()[0].lower() if person_name else ""

        # Strategy 1: Config override — explicit sensor per person
        bermuda_overrides = self.integration_entry.options.get(
            CONF_BERMUDA_AREA_SENSORS,
            self.integration_entry.data.get(CONF_BERMUDA_AREA_SENSORS, {})
        ) or {}
        override_sensor = bermuda_overrides.get(person_name) or bermuda_overrides.get(normalized_name)
        if override_sensor:
            if self.hass.states.get(override_sensor):
                _LOGGER.debug("Found Bermuda area sensor for %s via config override: %s", person_name, override_sensor)
                return override_sensor
            _LOGGER.warning("Configured Bermuda sensor %s for %s not found in HA", override_sensor, person_name)

        # Strategy 2: Private BLE derivation — find device_tracker from private_ble_device
        ent_reg = er.async_get(self.hass)
        for entity_entry in ent_reg.entities.values():
            if (entity_entry.platform == "private_ble_device"
                and entity_entry.domain == "device_tracker"
                and (first_name in entity_entry.entity_id or normalized_name in entity_entry.entity_id)):
                # Derive area sensor: sensor.{object_id}_area
                object_id = entity_entry.entity_id.split(".", 1)[1]
                area_sensor = f"sensor.{object_id}_area"
                if self.hass.states.get(area_sensor):
                    _LOGGER.debug("Found Bermuda area sensor for %s via private_ble: %s", person_name, area_sensor)
                    return area_sensor

        # Strategy 3: Minimal fallback — two common patterns
        patterns = [
            f"sensor.{first_name}_iphone_area",
            f"sensor.{normalized_name}_area",
        ]
        for pattern in patterns:
            if self.hass.states.get(pattern):
                _LOGGER.debug("Found Bermuda area sensor for %s: %s", person_name, pattern)
                return pattern

        # Strategy 4: Registry fallback — search Bermuda platform entities
        for entity_id, entity_entry in ent_reg.entities.items():
            if (entity_id.startswith("sensor.")
                and entity_id.endswith("_area")
                and "bermuda" in (entity_entry.platform or "")
                and (first_name in entity_id or normalized_name in entity_id)):
                _LOGGER.debug("Found Bermuda area sensor via registry for %s: %s", person_name, entity_id)
                return entity_id

        _LOGGER.warning("No Bermuda area sensor found for %s (tried: config, private_ble, patterns, registry)", person_name)
        return None

    # ==========================================================================
    # v3.2.4: FIXED CONFIDENCE CALCULATION
    # ==========================================================================

    async def _calculate_confidence(self, person_name: str, bermuda_area: str, resolved_room: str) -> float:
        """
        Calculate confidence score for person location based on Bermuda distance sensors.
        
        v3.2.4 FIX: Uses bermuda_area (scanner location) for scanner matching,
        not resolved_room (which may be different due to three-tier resolution).
        
        Algorithm:
        1. Find all Bermuda distance sensors for this person
        2. Find scanners in the bermuda_area
        3. Count how many see the device within high confidence distance
        4. Return tiered confidence based on scanner agreement
        """
        try:
            # Get Bermuda distance sensors for this person
            # v3.6.17: Only scan Bermuda entities instead of ALL entities
            ent_reg = er.async_get(self.hass)
            normalized_person = person_name.lower().replace(" ", "_")
            person_no_sep = person_name.lower().replace(" ", "")
            distance_sensors = []

            bermuda_entries = self.hass.config_entries.async_entries("bermuda")
            for be in bermuda_entries:
                for entity_entry in er.async_entries_for_config_entry(
                    ent_reg, be.entry_id
                ):
                    eid = entity_entry.entity_id
                    if (eid.startswith("sensor.") and
                        "distance_to_" in eid and
                        (normalized_person in eid or person_no_sep in eid)):
                        distance_sensors.append(eid)
                        # Auto-enable disabled sensors inline
                        if entity_entry.disabled:
                            ent_reg.async_update_entity(eid, disabled_by=None)
                            _LOGGER.info("Auto-enabled Bermuda distance sensor: %s", eid)

            if not distance_sensors:
                _LOGGER.debug("No Bermuda distance sensors found for %s", person_name)
                return 0.5  # Medium confidence - detected via area sensor but no distance data
            
            # v3.2.4 FIX: Get scanners in the BERMUDA area (where the person was detected)
            # Not the resolved room, which may be different
            area_scanners = await self._get_area_scanners(bermuda_area)
            
            if not area_scanners:
                _LOGGER.debug("No BLE scanners found in area %s", bermuda_area)
                return 0.5
            
            # Count scanners that see device within confidence distances
            close_scanners = 0
            very_close_scanners = 0
            detected_by_any = False
            # v3.6.21: Derive "very close" threshold from configurable high_confidence_distance
            very_close_threshold = self.high_confidence_distance / 2
            # v3.6.24: Track closest area scanner distance for music following
            closest_area_distance = None

            for sensor_id in distance_sensors:
                sensor_state = self.hass.states.get(sensor_id)
                if not sensor_state or sensor_state.state in ("unknown", "unavailable"):
                    continue

                detected_by_any = True

                try:
                    distance_ft = float(sensor_state.state)

                    # Extract scanner name from sensor_id
                    # Pattern: sensor.{person}_iphone_distance_to_{scanner_name}
                    scanner_name = sensor_id.split("distance_to_")[-1]
                    scanner_name_normalized = scanner_name.lower().replace("-", "_")

                    # Check if this scanner is in the area
                    is_area_scanner = any(
                        scanner_name_normalized in s.lower() or
                        s.lower() in scanner_name_normalized
                        for s in area_scanners
                    )

                    if is_area_scanner:
                        # v3.6.24: Track closest distance
                        if closest_area_distance is None or distance_ft < closest_area_distance:
                            closest_area_distance = distance_ft
                        if distance_ft < very_close_threshold:
                            very_close_scanners += 1
                            _LOGGER.debug(
                                "Very close scanner: %s (%.1f ft) for %s",
                                scanner_name, distance_ft, person_name
                            )
                        elif distance_ft < self.high_confidence_distance:
                            close_scanners += 1
                            _LOGGER.debug(
                                "Close scanner: %s (%.1f ft) for %s",
                                scanner_name, distance_ft, person_name
                            )

                except (ValueError, IndexError) as e:
                    _LOGGER.debug("Error parsing distance sensor %s: %s", sensor_id, e)
                    continue

            # v3.6.24: Store closest distance in person data for downstream consumers
            # v4.5.5: guard self.data is None — DataUpdateCoordinator.data is None
            # before first successful refresh; matches the `if not self.data or …`
            # guard used at every other access site in this file.
            if self.data and person_name in self.data and closest_area_distance is not None:
                self.data[person_name]["closest_distance"] = closest_area_distance

            # Calculate confidence based on scanner count and distance
            if very_close_scanners >= 1:
                return 0.9  # At least one scanner very close (<5ft)
            elif close_scanners >= 2:
                return 0.9  # Multiple scanners confirm presence
            elif close_scanners == 1:
                return 0.7  # Single scanner confirmation
            elif detected_by_any:
                return 0.5  # Detected but scanner matching uncertain
            else:
                return 0.3  # Weak detection
            
        except Exception as e:
            _LOGGER.error("Error calculating confidence for %s in %s: %s", person_name, bermuda_area, e)
            return 0.5

    async def _get_area_scanners(self, area_name: str) -> list[str]:
        """
        Get list of BLE scanner device names in a Home Assistant area.
        
        v3.2.4 FIX: Searches by area name, not by room entry.
        Looks for Shelly, ESPHome, and other BLE-capable devices.
        """
        try:
            area_reg = ar.async_get(self.hass)
            dev_reg = dr.async_get(self.hass)
            
            # Find area by name
            area_entry = None
            for area in area_reg.async_list_areas():
                if (area.name == area_name or 
                    area.name.lower().replace(" ", "_") == area_name.lower().replace(" ", "_") or
                    area.id == area_name):
                    area_entry = area
                    break
            
            if not area_entry:
                _LOGGER.debug("Area not found: %s", area_name)
                return []
            
            scanners = []

            # v3.6.18: Only scan BLE integration devices instead of ALL devices
            ble_domains = ("shelly", "esphome", "bluetooth", "bermuda")
            for domain in ble_domains:
                for ce in self.hass.config_entries.async_entries(domain):
                    for device in dr.async_entries_for_config_entry(
                        dev_reg, ce.entry_id
                    ):
                        if device.area_id != area_entry.id:
                            continue
                        scanner_name = device.name_by_user or device.name
                        if scanner_name:
                            normalized_name = scanner_name.lower().replace(" ", "_").replace("-", "_")
                            scanners.append(normalized_name)
                            _LOGGER.debug("Found BLE scanner in area %s: %s", area_name, scanner_name)
            
            return scanners
            
        except Exception as e:
            _LOGGER.error("Error getting area scanners for %s: %s", area_name, e)
            return []

    # ==========================================================================
    # PUBLIC API METHODS
    # ==========================================================================

    def get_person_location(self, person_name: str) -> str:
        """Get current location for a person."""
        if not self.data or person_name not in self.data:
            return "unknown"
        return self.data[person_name]["location"]

    def get_person_confidence(self, person_name: str) -> float:
        """Get confidence score for a person's location."""
        if not self.data or person_name not in self.data:
            return 0.0
        return self.data[person_name]["confidence"]
    
    def get_person_previous_location(self, person_name: str) -> str:
        """Get previous location for a person."""
        if not self.data or person_name not in self.data:
            return "unknown"
        return self.data[person_name].get("previous_location", "unknown")
    

    def _update_recent_path(self, old_path: list[str], new_location: str, old_location: str) -> list[str]:
        """
        Update the recent path list with new location.
        
        v3.2.8.1: Implements path tracking for debugging movement patterns.
        
        Args:
            old_path: Previous path list
            new_location: New room location
            old_location: Previous room location
        
        Returns:
            Updated path list (max length = MAX_RECENT_PATH_LENGTH)
        """
        # Don't add to path if location didn't change
        if new_location == old_location:
            return old_path
        
        # Don't track non-room locations in path
        if new_location in ("unknown", "away", "home", ""):
            return old_path
        
        # Add new location to front of path
        new_path = [new_location] + old_path
        
        # Trim to max length
        return new_path[:MAX_RECENT_PATH_LENGTH]

    def get_person_previous_seen(self, person_name: str) -> datetime | None:
        """Get when person was last seen (last_changed timestamp)."""
        if not self.data or person_name not in self.data:
            return None
        return self.data[person_name].get("last_changed")
    def get_person_previous_location_time(self, person_name: str) -> datetime | None:
        """
        Get when person was last seen in their previous location.
        
        v3.2.8.1: Fixed - now returns previous_location_time instead of last_changed.
        This is what the "Previous Seen" sensor should display.
        
        Args:
            person_name: Name of person to check
        
        Returns:
            Timestamp when person was last in their previous location, or None
        """
        if not self.data or person_name not in self.data:
            return None
        return self.data[person_name].get("previous_location_time")

    def seed_previous_location(self, person_name: str, location: str) -> None:
        """Seed previous_location from RestoreEntity on startup.

        v4.6.9: Idempotent — only writes when the in-memory value is
        None / "unknown" / "Unknown" / "away" / "Away" / missing.
        Never clobbers live data populated by the coordinator.

        Args:
            person_name: Key in self.data (matches existing getter convention).
            location:    The persisted location string from the last HA state.
        """
        if self.data is None:
            # DataUpdateCoordinator hasn't run its first refresh yet; nothing
            # to seed into — the first real update will overwrite anyway.
            _LOGGER.debug(
                "seed_previous_location: skip %s — coordinator data not yet initialised",
                person_name,
            )
            return
        self.data.setdefault(person_name, {})
        current = self.data[person_name].get("previous_location")
        if current in (None, "unknown", "Unknown", "away", "Away", ""):
            self.data[person_name]["previous_location"] = location
            _LOGGER.debug(
                "seed_previous_location: %s ← %r (was %r)",
                person_name, location, current,
            )
        else:
            _LOGGER.debug(
                "seed_previous_location: skip %s — live value %r present",
                person_name, current,
            )

    def seed_previous_location_time(self, person_name: str, time: datetime) -> None:
        """Seed previous_location_time from RestoreEntity on startup.

        v4.6.9: Idempotent — only writes when the in-memory value is None /
        missing. Never clobbers live data.

        Args:
            person_name: Key in self.data.
            time:        Timezone-aware datetime parsed by dt_util.parse_datetime.
        """
        if self.data is None:
            _LOGGER.debug(
                "seed_previous_location_time: skip %s — coordinator data not yet initialised",
                person_name,
            )
            return
        self.data.setdefault(person_name, {})
        # v4.6.9 review MEDIUM#1: coerce naive datetime to UTC to avoid
        # tz-aware/naive subtraction errors downstream (Bug Class #21).
        if time.tzinfo is None:
            time = dt_util.as_utc(time)
        current = self.data[person_name].get("previous_location_time")
        if current is None:
            self.data[person_name]["previous_location_time"] = time
            _LOGGER.debug(
                "seed_previous_location_time: %s ← %s (was None)",
                person_name, time,
            )
        else:
            _LOGGER.debug(
                "seed_previous_location_time: skip %s — live value %s present",
                person_name, current,
            )

    def get_room_occupants(self, room_name: str) -> list[str]:
        """
        Get list of people currently in a room.
        
        v3.2.4: Uses resolved room names from three-tier resolution.
        Falls back to fuzzy matching for compatibility.
        v3.2.6: Lowered confidence threshold from 0.5 to 0.3
        v3.2.6: Added comprehensive diagnostic logging
        """
        if not self.data:
            _LOGGER.debug(
                "🔍 ROOM OCCUPANTS [%s]: No person data available (coordinator.data is empty)",
                room_name
            )
            return []
        
        occupants = []
        room_lower = room_name.lower().replace(" ", "_")
        
        _LOGGER.debug(
            "🔍 ROOM OCCUPANTS [%s]: Checking %d tracked persons, room_lower='%s'",
            room_name, len(self.data), room_lower
        )
        
        for person_name, person_info in self.data.items():
            location = person_info.get("location", "")
            confidence = person_info.get("confidence", 0)
            
            # Skip non-room locations
            if not location or location in ("unknown", "away", "home"):
                _LOGGER.debug(
                    "🔍 ROOM OCCUPANTS [%s]: %s skipped - non-room location '%s'",
                    room_name, person_name, location
                )
                continue
            
            # Check confidence threshold (v3.2.6: lowered from 0.5 to 0.3)
            if confidence < 0.3:
                _LOGGER.debug(
                    "🔍 ROOM OCCUPANTS [%s]: %s skipped - confidence %.2f < 0.3 threshold",
                    room_name, person_name, confidence
                )
                continue
            
            location_lower = location.lower().replace(" ", "_")
            
            # v3.6.19: Exact match only — three-tier resolution already
            # maps Bermuda areas to canonical room names. Fuzzy matching
            # caused false positives (e.g. "den" matching "garden").
            is_match = (room_lower == location_lower)
            
            if is_match:
                occupants.append(person_name)
                _LOGGER.debug(
                    "🔍 ROOM OCCUPANTS [%s]: ✓ MATCH - %s at '%s' (confidence: %.2f)",
                    room_name, person_name, location, confidence
                )
            else:
                _LOGGER.debug(
                    "🔍 ROOM OCCUPANTS [%s]: %s NO MATCH - location '%s' vs room '%s'",
                    room_name, person_name, location_lower, room_lower
                )
        
        _LOGGER.debug(
            "🔍 ROOM OCCUPANTS [%s]: Result = %s (%d people)",
            room_name, occupants, len(occupants)
        )
        
        return occupants
    
    # Alias for compatibility with v3.2.0 sensor.py
    def get_persons_in_room(self, room_name: str) -> list[str]:
        """Alias for get_room_occupants - for v3.2.0 compatibility."""
        return self.get_room_occupants(room_name)

    def is_room_direct_ble(self, room_name: str) -> bool:
        """
        Return True if room has direct (Tier 1) BLE scanner coverage.

        A room is Tier 1 when its own CONF_AREA_ID matches a Bermuda area
        and it does NOT configure CONF_SCANNER_AREAS. Rooms that configure
        CONF_SCANNER_AREAS are Tier 2 (shared scanner from an adjacent room)
        and return False — BLE alone should not drive occupancy for these
        rooms without motion/mmWave confirmation.

        Uses cached _direct_ble_rooms set built during _build_scanner_room_map.
        """
        return room_name.lower().replace(" ", "_") in self._direct_ble_rooms

    def get_ble_tier(self, room_name: str) -> int:
        """Return BLE scanner-resolution tier for a room.

        v4.7.16 D1: derived attribute over CONF_SCANNER_AREAS classification.

        Returns:
            1 — direct / dense (room has own scanner; member of _direct_ble_rooms)
            2 — borrowing / sparse (CONF_SCANNER_AREAS configured on this room
                AND CONF_AREA_ID set; relies on a neighbor's scanner)
            0 — neither (no area_id, or no BLE classification)

        Read-only consumer of `_build_scanner_room_map` output. Lazy at read
        time per Bug Class #46 doctrine — no migration helper, fail-safe to 0
        when scanner map has not been built yet.

        Note: this method uses "ble_tier" to distinguish from
        ZonePresenceTracker's Tier 1/2/3 signal-class vocabulary. See file
        header comment for the scanner-resolution Tier 1/2/3 vocabulary.
        """
        norm = (room_name or "").lower().replace(" ", "_")
        if not norm:
            return 0
        # Tier 1 short-circuit: present in the cached direct-BLE set.
        if norm in self._direct_ble_rooms:
            return 1
        # Tier 2 / 0: walk room entries to find this room's CONF_SCANNER_AREAS.
        try:
            entries = self.hass.config_entries.async_entries(DOMAIN)
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.debug("get_ble_tier: config entry walk failed: %s", exc)
            return 0
        # Post-review A4 (MEDIUM): surface duplicate ROOM entries with the
        # same room_name as a debug log. Behavior is unchanged (we return on
        # the FIRST match — same as v3.8.9's _build_scanner_room_map), but
        # the debug line gives operators a trail when "ble_tier seems wrong"
        # turns out to be a duplicate-add via the UI.
        _matched_count = 0
        _first_tier = 0
        for entry in entries:
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            entry_room = (entry.data.get("room_name") or "").lower().replace(" ", "_")
            if entry_room != norm:
                continue
            config = {**entry.data, **entry.options}
            area_id = config.get(CONF_AREA_ID)
            scanner_areas = config.get(CONF_SCANNER_AREAS) or []
            if scanner_areas and area_id:
                _tier_here = 2
            else:
                _tier_here = 0
            _matched_count += 1
            if _matched_count == 1:
                _first_tier = _tier_here
            elif _matched_count == 2:
                _LOGGER.debug(
                    "get_ble_tier: room_name=%r has multiple ROOM entries "
                    "(misconfig?). Using tier from first-walk entry (%d). "
                    "Subsequent duplicate entries ignored.",
                    room_name, _first_tier,
                )
        if _matched_count >= 1:
            return _first_tier
        return 0

    def get_zone_occupants(self, zone_rooms: list[str]) -> list[str]:
        """
        Get list of people currently in any room within a zone.
        """
        if not self.data:
            return []
        
        occupants = set()
        for room_name in zone_rooms:
            room_occupants = self.get_room_occupants(room_name)
            occupants.update(room_occupants)
        
        return sorted(list(occupants))
    
    # Alias for compatibility with v3.2.0 aggregation.py
    def get_persons_in_zone(self, zone_rooms: list[str]) -> list[str]:
        """Alias for get_zone_occupants - for v3.2.0 compatibility."""
        return self.get_zone_occupants(zone_rooms)

    # ==========================================================================
    # v3.2.6: DIAGNOSTIC DATA
    # ==========================================================================

    def get_diagnostic_data(self) -> dict[str, Any]:
        """
        Get diagnostic information about person tracking coordinator.
        
        v3.2.6: Added for troubleshooting staleness and matching issues.
        """
        return {
            "tracked_persons": self.tracked_persons,
            "data_available": self.data is not None,
            "person_count": len(self.data) if self.data else 0,
            "last_update": self.last_update_success_time.isoformat() if hasattr(self, 'last_update_success_time') and self.last_update_success_time else "unknown",
            "update_interval_seconds": UPDATE_INTERVAL,
            "area_mappings_count": len(self._area_id_to_room),
            "scanner_mappings_count": len(self._scanner_to_rooms),
            "room_coordinators_count": len(self._room_coordinators),
            "confidence_threshold": 0.3,
            "persons_data": {
                name: {
                    "location": info.get("location", "unknown"),
                    "confidence": info.get("confidence", 0),
                    "method": info.get("method", "unknown"),
                    "bermuda_area": info.get("bermuda_area", "N/A"),
                }
                for name, info in (self.data or {}).items()
            }
        }

    def get_tracked_person_count(self) -> int:
        """
        Get count of tracked people who are home (not away/unknown).
        
        v3.2.6: Added for whole-house occupant count sensor.
        """
        if not self.data:
            return 0
        
        count = 0
        for person_info in self.data.values():
            location = person_info.get("location", "unknown")
            if location not in ("unknown", "away"):
                count += 1
        
        return count


# _fire_frozen_tracker_nm DELETED 2026-08-10 — D3 detector was
# structurally unreachable (see const.py tombstone).


"""Zone management for HVAC Coordinator.

Auto-discovers HVAC zones from CONF_ZONE_THERMOSTAT config on URA zones,
aggregates room conditions (temperature, humidity, occupancy) per zone,
and provides zone-aware control.

v3.8.0-H1: Initial implementation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_ENTRY_TYPE,
    CONF_ROOM_NAME,
    CONF_ZONE_ROOMS,
    CONF_ZONE_THERMOSTAT,
    DOMAIN,
    ENTRY_TYPE_ROOM,
    ENTRY_TYPE_ZONE,
    ENTRY_TYPE_ZONE_MANAGER,
)
from .hvac_const import (
    CONF_HVAC_AC_LOAD_SENSOR,
    CONF_HVAC_AC_RAMP_ZONE_ENABLED,
    CONF_HVAC_THERMOSTAT_MIN_DELTA_F,
    DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED,
    DEFAULT_HVAC_THERMOSTAT_MIN_DELTA_F,
    HVAC_THERMOSTAT_MIN_DELTA_MAX_F,
    HVAC_THERMOSTAT_MIN_DELTA_MIN_F,
    DUTY_CYCLE_WINDOW_SECONDS,
    HVAC_LIVE_ROOM_TRANSIENT_GRACE_S,
)

_LOGGER = logging.getLogger(__name__)


def _min_delta_from(cfg: Any) -> float:
    """W1-C P2: the configured thermostat min heat/cool gap (°F), default
    5; a malformed value falls back to the default."""
    try:
        val = float((cfg or {}).get(
            CONF_HVAC_THERMOSTAT_MIN_DELTA_F, DEFAULT_HVAC_THERMOSTAT_MIN_DELTA_F,
        ))
    except (TypeError, ValueError):
        return float(DEFAULT_HVAC_THERMOSTAT_MIN_DELTA_F)
    if not val > 0:  # 0 / negative / NaN -> the default (as before)
        return float(DEFAULT_HVAC_THERMOSTAT_MIN_DELTA_F)
    clamped = min(max(val, HVAC_THERMOSTAT_MIN_DELTA_MIN_F), HVAC_THERMOSTAT_MIN_DELTA_MAX_F)
    if clamped != val and val not in _MIN_DELTA_CLAMP_LOGGED:
        # Operator ruling 2026-10-05: one INFO per stored out-of-range value.
        _MIN_DELTA_CLAMP_LOGGED.add(val)
        _LOGGER.info(
            "HVAC: stored thermostat min heat/cool gap %.1f F is outside "
            "%.0f-%.0f F; using %.1f F", val, HVAC_THERMOSTAT_MIN_DELTA_MIN_F,
            HVAC_THERMOSTAT_MIN_DELTA_MAX_F, clamped,
        )
    return float(clamped)


_MIN_DELTA_CLAMP_LOGGED: set[float] = set()


def _profile_attrs(hass: Any, entity_id: str | None) -> dict[str, Any]:
    """W1-C P2 D1 display attrs (never raises)."""
    try:
        from .hvac_strategy import profile_info  # noqa: PLC0415
        prof, src = profile_info(hass, entity_id)
    except Exception:  # noqa: BLE001
        prof, src = None, None
    return {"thermostat_profile": prof, "profile_source": src}


def _coerce_hold_override(raw: Any) -> int | None:
    """Coerce a per-room HVAC hold override to a non-negative int, or None.

    Blank / missing / non-numeric values return None so the resolver
    falls through to the ROOM_TYPE_HVAC_HOLD[_NIGHT] table default.
    Explicit 0 is preserved (legitimate never-hold value; only the
    hallway table default uses it today).
    """
    if raw is None or raw == "":
        return None
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None
    if val < 0:
        return None
    return val


@dataclass
class RoomCondition:
    """Aggregated condition for a single room."""

    room_name: str
    temperature: float | None = None
    humidity: float | None = None
    occupied: bool = False
    # HVAC-ZONE-CONDITIONING-DEMAND-1 D1 (2026-09-16): sibling of `.occupied`
    # for the HVAC-occupancy denomination. Grace-held STATE_OCCUPIED + per-room
    # tail-hold, with CIRCULATION EXCLUSION (room_type == "hallway" -> always
    # False). Populated by ZoneManager.update_room_conditions from the D1 state
    # machine (self._hvac_armed / self._hvac_tail_until). Original `.occupied`
    # is UNCHANGED and remains the lighting-fused signal.
    hvac_occupied: bool = False
    weight: float = 1.0
    # v4.7.8 D3: Egress-window state per room. `window_sensor` is the raw
    # binary_sensor entity_id from CONF_WINDOW_SENSORS; `window_state` is
    # its last-observed state ("on"/"off"/None). `is_egress_window` is the
    # per-room flag from CONF_IS_EGRESS_WINDOW (lazy default True).
    window_sensor: str | None = None
    window_state: str | None = None
    is_egress_window: bool = True
    room_entry_id: str | None = None


@dataclass
class ZoneState:
    """State of a single HVAC zone."""

    zone_id: str
    zone_name: str
    climate_entity: str
    rooms: list[str] = field(default_factory=list)

    # Current climate entity state
    preset_mode: str = ""
    hvac_mode: str = ""
    hvac_action: str = ""
    current_temperature: float | None = None
    current_humidity: float | None = None
    target_temp_high: float | None = None
    target_temp_low: float | None = None

    # Aggregated room conditions
    room_conditions: list[RoomCondition] = field(default_factory=list)

    # Override tracking
    override_count_today: int = 0
    ac_reset_count_today: int = 0
    last_override_direction: str = ""  # "cooler" or "warmer" or ""
    last_stuck_detected: str = ""  # ISO timestamp when stuck cycle detected

    # v3.17.0: Zone Intelligence fields
    # D1: Vacancy management
    last_occupied_time: datetime | None = None
    vacancy_sweep_done: bool = False
    vacancy_sweep_enabled: bool = True
    zone_persons: list[str] = field(default_factory=list)
    zone_cameras: list[str] = field(default_factory=list)
    camera_face_arrivals_today: int = 0

    # D4: Zone presence state machine
    zone_presence_state: str = "unknown"

    # D5: Duty cycle enforcement
    runtime_seconds_this_window: float = 0.0
    window_start: datetime | None = None
    runtime_exceeded: bool = False

    # D6: Max-occupancy-duration failsafe
    continuous_occupied_since: datetime | None = None

    # HVAC fast occupancy response D5 (v5.103.20, plan §4.2 step 6 / §5.2):
    # rooms of this zone whose evidence episode is live but not yet
    # persisted (cold rooms on the away edge). S1 HOLDS the zone's preset
    # while this is non-empty AND the zone is otherwise HVAC-empty.
    # `pending_hold_since` / `pending_hold_s_today` measure that exposure
    # (plan §7.1); the per-zone D5 lapse counter lives on the ZoneManager.
    hvac_pending_arm_rooms: list[str] = field(default_factory=list)
    pending_hold_since: datetime | None = None
    pending_hold_s_today: float = 0.0

    # v4.2.2: Zone entry dwell — when current occupancy session started
    current_session_start: datetime | None = None

    # v4.5.11: AC ramp-down (energy-aware) — per-zone runtime state
    # ac_load_sensor: entity_id of the kW sensor watching this AC's draw.
    #   "" = unset = feature OFF for this zone (graceful degrade).
    # kwh_rate_threshold: per-zone slider value, defaults to 0.8 kW (3-ton
    #   heuristic). Tune up for larger units.
    # ramp_zone_enabled: per-zone opt-out (master ON + zone OFF = skip).
    # kwh_samples_above_threshold: 3-sample debounce counter.
    # last_overshoot_started: ISO timestamp of first sample in current
    #   overshoot window — gates the time-sustained check.
    # ramp_state: state-machine label exposed via D7 sensor.
    # last_kwh_rate / last_kwh_rate_ts: latest reading for D7 sensor.
    # nudge_kwh_rate_before: captured at nudge fire for D8 kWh-avoided math.
    # last_kwh_stale_warned_ts: rate-limit stale-sensor warnings.
    ac_load_sensor: str = ""
    # HVAC W1-C P2: the thermostat's own min heat/cool gap (Zone ->
    # Thermostat, rung 2). Read only by range-holding adapters (ecobee).
    thermostat_min_delta_f: float = DEFAULT_HVAC_THERMOSTAT_MIN_DELTA_F
    kwh_rate_threshold: float = 0.8
    ramp_zone_enabled: bool = True
    kwh_samples_above_threshold: int = 0
    last_overshoot_started: str = ""
    ramp_state: str = "idle"
    last_kwh_rate: float | None = None
    last_kwh_rate_ts: str = ""
    nudge_kwh_rate_before: float | None = None
    last_kwh_stale_warned_ts: str = ""

    # v4.5.12 D7: per-zone last-action tracking for the
    # `sensor.ura_hvac_ac_ramp_last_action_<zone>` sensor. Updated by
    # OverrideArrester action methods (_perform_soft_nudge, _restore_*,
    # _evaluate_nudge_outcome, _engage_lockout, etc.) so the sensor can
    # read in-memory state without per-tick DB queries.
    last_action_type: str = ""
    last_action_ts: str = ""
    last_action_triggered_by: str = ""
    last_action_kwh_before: float | None = None
    last_action_kwh_after: float | None = None

    @property
    def any_room_occupied(self) -> bool:
        """Return True if any room in this zone is occupied."""
        return any(r.occupied for r in self.room_conditions)

    @property
    def any_room_hvac_occupied(self) -> bool:
        """HVAC-occupancy denomination (HVAC-ZONE-CONDITIONING-DEMAND-1 D1).

        Sibling of `any_room_occupied`, keyed on `RoomCondition.hvac_occupied`
        (grace-held STATE_OCCUPIED with per-room tail-hold; hallway rooms
        excluded). This is the correct signal for conditioning-decision code
        paths (preset-flip retreat, DPM caller-side point-gate, night-trust
        guard). Lighting/fan/cover/confidence surfaces continue to read the
        lighting-fused `.occupied`.
        """
        return any(r.hvac_occupied for r in self.room_conditions)

    @property
    def occupied_rooms(self) -> list[str]:
        """Return list of occupied room names."""
        return [r.room_name for r in self.room_conditions if r.occupied]

    @property
    def avg_temperature(self) -> float | None:
        """Weighted average temperature across rooms."""
        temps = [
            (r.temperature, r.weight)
            for r in self.room_conditions
            if r.temperature is not None
        ]
        if not temps:
            return self.current_temperature
        total_weight = sum(w for _, w in temps)
        if total_weight == 0:
            return None
        return sum(t * w for t, w in temps) / total_weight

    @property
    def avg_humidity(self) -> float | None:
        """Average humidity across rooms."""
        vals = [r.humidity for r in self.room_conditions if r.humidity is not None]
        if not vals:
            return self.current_humidity
        return sum(vals) / len(vals)


class ZoneManager:
    """Discovers and manages HVAC zones.

    Auto-discovers zones from CONF_ZONE_THERMOSTAT config entries.
    Aggregates room conditions per zone from URA room data.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize zone manager."""
        self.hass = hass
        self._zones: dict[str, ZoneState] = {}
        # HVAC-ZONE-CONDITIONING-DEMAND-1 D1 (2026-09-16): per-room state for
        # the HVAC-occupancy tail-hold producer. `_hvac_armed[room]` latches
        # True on a rising `STATE_OCCUPIED` edge and rides purely on grace-held
        # STATE_OCCUPIED + the tail expiry, NEVER on raw substrate kind reads
        # (CRIT-1 closure: kind is not consulted on the D1 path at all —
        # transit rejection is handled by the CIRCULATION EXCLUSION on
        # room_type == "hallway"). `_hvac_tail_until[room]` is None while
        # STATE_OCCUPIED is held; on the falling edge it is set to
        # `now + effective_hold(room, house_state)` and released once now
        # crosses the expiry. Keyed by room_name; lifespan matches the
        # ZoneManager (survives config-entry reload only because the
        # ZoneManager is re-created).
        self._hvac_armed: dict[str, bool] = {}
        self._hvac_tail_until: dict[str, datetime] = {}
        self._hvac_prev_state_occupied: dict[str, bool] = {}
        # Producer diagnostics: last-known room_type per room and the source
        # of arm-attribution ("edge" / "held" / "tail" / "hallway_excluded").
        self._hvac_arm_source: dict[str, str] = {}
        # HVAC-ZONE-CONDITIONING-DEMAND-1 D-HIGH-1 fix-up (2026-09-17,
        # SUPERSEDED by HVAC-DEGRADED-ROOM-TRIPWIRE-1 2026-09-26):
        # `_hvac_seen` still tracks rooms for which the D1 producer has
        # produced a value AT LEAST ONCE since ZoneManager construction.
        # A zone is HVAC-ESTABLISHED iff every LIVE room (per the
        # `_classify_all_rooms` denominator — LOADED, coordinator-present,
        # NOT sticky-failed / disabled / entry-removed / transient) is in
        # `_hvac_seen`. Rooms classified EXCLUDED leave the denominator;
        # TRANSIENT rooms BLOCK outright. An unestablished zone must NOT
        # drive a night-trust retreat (D7/row-1 fail-open) — the
        # ~5x/night CM reload otherwise wipes in-memory D1 state,
        # releases boot-settle on the reload path, and
        # `last_occupied_time` seeded past-grace causes a first-tick
        # retreat of a sleeping bedroom.
        self._hvac_seen: set[str] = set()

        # HVAC fast occupancy response (v5.103.20, plan §4.2): the evidence
        # rule's OWN state. The three dicts above (`_hvac_armed`,
        # `_hvac_tail_until`, `_hvac_prev_state_occupied`) are owned by the
        # SHADOW machine alone (INV-5); the evidence branch never writes them.
        #   _hvac_output[room]   -> the room's final hvac_occupied on the last pass
        #   _hvac_rule[room]     -> "evidence" | "night" | "legacy" on the last pass
        #   _hvac_day_release_at -> last_evidence + evidence hold (None if no evidence)
        #   _hvac_shadow_release_at -> when the shadow last released the room
        #                              (tail expiry or the no-tail release instant)
        #   _hvac_last_ev / _hvac_last_active -> the evidence inputs of the last pass
        self._hvac_output: dict[str, bool] = {}
        self._hvac_rule: dict[str, str] = {}
        self._hvac_day_release_at: dict[str, datetime] = {}
        self._hvac_shadow_release_at: dict[str, datetime] = {}
        self._hvac_last_ev: dict[str, datetime | None] = {}
        self._hvac_last_active: dict[str, bool] = {}
        # D5 transit filter (plan §5b): per-room EPISODE state — an episode
        # is a chain of evidence stretches whose onsets fall within
        # J = min(hold_ev, W) of the previous evidence. A cold room (away
        # edge, output False, not exempt) arms only once its episode has
        # persisted for W. Never-armed episodes are excluded from E(Z).
        self._hvac_episode_start: dict[str, datetime] = {}
        self._hvac_episode_onsets: dict[str, list[datetime]] = {}
        self._hvac_episode_prev_ev: dict[str, datetime] = {}
        self._hvac_episode_closed_s: dict[str, float] = {}
        self._hvac_episode_active_s: dict[str, float] = {}
        self._hvac_pending: dict[str, bool] = {}
        self._hvac_ep_armed: dict[str, bool] = {}
        self._hvac_armed_at: dict[str, datetime] = {}
        self._hvac_arm_onset: dict[str, datetime] = {}
        self._hvac_arm_span_s: dict[str, float] = {}
        self._hvac_arm_class: dict[str, str] = {}
        # Stamped ONLY when an evidence-state True -> False ended an arm of
        # span >= W (or W == 0): the room-only return exemption anchor.
        self._hvac_ev_released_at: dict[str, datetime] = {}
        self._hvac_exempt_reason: dict[str, str | None] = {}
        self._hvac_cold: dict[str, bool] = {}
        self._hvac_dwell_s: dict[str, float] = {}
        # Per-zone: unarmed episodes that lapsed today (D5 C1-D metric).
        self.transit_filtered_today: dict[str, int] = {}
        # Pass-complete snapshots so `room_release_at` / `zone_away_due_at`
        # (exit timer, sync) can resolve a room's type / override / coordinator
        # without re-walking config entries.
        self._room_meta_last_pass: dict[str, dict[str, Any]] = {}
        self._room_coord_last_pass: dict[str, Any] = {}
        self._last_house_state: str | None = None

        # HVAC-DEGRADED-ROOM-TRIPWIRE-1 (2026-09-26): live-room establishment.
        # `_room_entry_by_name` maps ROOM room_name -> ConfigEntry, rebuilt at
        # the start of every `update_room_conditions` pass so `_classify_all_
        # rooms` can read `entry.state` / `entry.disabled_by` without a fresh
        # config-entries iteration. `_room_hvac_class[room_name] = (kind,
        # reason)` where kind is one of "live" | "transient" | "excluded".
        # `_room_non_loaded_since` seeds on first non-LOADED observation per
        # (boot, room); cleared on LOADED. `_coordinator_absent_this_pass`
        # is rebuilt every pass and holds rooms whose D1 producer took the
        # synthetic-empty branch (coordinator is None) — REV-2 D2's braces
        # against LOADED-but-coordinator-absent. `_pending_degraded_events`
        # queues transient→excluded and immediate-exclusion events for the
        # HVACCoordinator to drain via NM after the sync producer returns
        # (no create_task from a sync tick path). `_excluded_ever_notified`
        # is the debounce set per (boot, room). `_hvac_classification_ready`
        # is the fallback flag — while False (tests that don't drive
        # `update_room_conditions`) `is_zone_hvac_established` falls back to
        # the round-5 `_hvac_seen`-only semantics for backward compat.
        self._room_entry_by_name: dict[str, Any] = {}
        self._room_hvac_class: dict[str, tuple[str, str]] = {}
        self._room_non_loaded_since: dict[str, datetime] = {}
        self._coordinator_absent_this_pass: set[str] = set()
        self._pending_degraded_events: list[tuple[str, str]] = []
        self._excluded_ever_notified: set[str] = set()
        self._hvac_classification_ready: bool = False
        self._unknown_state_warned: set[str] = set()
        # FIX-UP item 1 (sticky failed exclusion): once a room enters
        # SETUP_ERROR / MIGRATION_ERROR / SETUP_RETRY it STAYS excluded
        # through subsequent SETUP_IN_PROGRESS phases (HA retry cycle:
        # SETUP_RETRY -> SETUP_IN_PROGRESS -> SETUP_RETRY every ~80s).
        # Only an observed LOADED transition clears it.
        self._sticky_failed_rooms: set[str] = set()
        # FIX-UP item 5: only emit degraded WARN+NM for rooms that belong
        # to at least one HVAC zone — classification runs over ALL ROOM
        # entries but hallway-only / unzoned rooms must not alert.
        self._rooms_in_any_zone: set[str] = set()

    @property
    def zones(self) -> dict[str, ZoneState]:
        """Return all discovered zones."""
        return self._zones

    @property
    def zone_count(self) -> int:
        """Return number of discovered zones."""
        return len(self._zones)

    def _zone_id_from_thermostat(self, climate_entity: str, fallback_num: int) -> str:
        """Derive zone_id from the thermostat entity name.

        If the entity contains "zone_N", uses that number to match
        physical thermostat labeling. Otherwise auto-numbers sequentially.
        Guarantees no collisions with already-assigned zone IDs.
        """
        match = re.search(r"(?:^|[_.\s])zone[_\s]?(\d+)", climate_entity)
        if match:
            candidate = f"zone_{match.group(1)}"
            if candidate not in self._zones:
                return candidate
            # Collision — fall through to auto-number

        # Auto-number: find next unused ID
        n = fallback_num
        while f"zone_{n}" in self._zones:
            n += 1
        return f"zone_{n}"

    async def async_discover_zones(self) -> int:
        """Discover HVAC zones from zone config entries.

        Reads CONF_ZONE_THERMOSTAT from:
        1. Zone Manager entry zones dict (current architecture, v3.6.0+)
        2. Legacy individual ENTRY_TYPE_ZONE entries (pre-v3.6.0 fallback)

        Returns count of discovered zones.
        """
        from datetime import timedelta
        from .hvac_const import DEFAULT_VACANCY_GRACE_MINUTES

        self._zones.clear()
        next_zone_num = 0  # Fallback counter for thermostats without a zone number

        # Build entry_id -> room_name mapping for Zone Manager rooms
        entry_id_to_room_name: dict[str, str] = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                room_name = entry.data.get(CONF_ROOM_NAME, "")
                if room_name:
                    entry_id_to_room_name[entry.entry_id] = room_name

        # 1. Read from Zone Manager entry (primary source)
        # Multiple URA zones can share a thermostat (e.g., Entertainment +
        # Master Suite both served by StudyB Zone 1). When this happens,
        # merge their rooms into a single HVAC zone so occupancy in ANY
        # of the mapped zones keeps the thermostat active.
        #
        # LOCKSTEP NOTE (Bug Class #36): the module-level helper
        # `iter_canonical_hvac_zones` at module-end replicates this
        # merge logic for use during platform setup (before coordinator
        # init). Any change to merge semantics here MUST be replicated
        # there. The lockstep equivalence test in
        # test_v4513_1_zone_dedup.py asserts both code paths agree.
        thermostat_to_zone_id: dict[str, str] = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ZONE_MANAGER:
                continue

            merged = {**entry.data, **entry.options}
            zones_dict = merged.get("zones", {})

            for zm_zone_name, zone_cfg in zones_dict.items():
                thermostat = zone_cfg.get(CONF_ZONE_THERMOSTAT)
                if not thermostat:
                    continue

                # Convert entry IDs to room names
                raw_rooms = zone_cfg.get(CONF_ZONE_ROOMS, [])
                room_names: list[str] = []
                if isinstance(raw_rooms, list):
                    for r in raw_rooms:
                        name = entry_id_to_room_name.get(r)
                        if name:
                            room_names.append(name)
                        else:
                            _LOGGER.warning(
                                "HVAC: Zone %s has unknown room entry %s",
                                zm_zone_name, r,
                            )

                from .hvac_const import CONF_ZONE_VACANCY_SWEEP_ENABLED, CONF_ZONE_PERSONS, CONF_ZONE_CAMERAS
                sweep_enabled = zone_cfg.get(CONF_ZONE_VACANCY_SWEEP_ENABLED, True)
                zone_persons = zone_cfg.get(CONF_ZONE_PERSONS, [])
                zone_cameras = zone_cfg.get(CONF_ZONE_CAMERAS, [])
                # v4.5.11: AC ramp-down per-zone form fields (imports at
                # module-level so the legacy ENTRY_TYPE_ZONE fallback below
                # can use them too — Bug Class #33 prevention).
                ac_load_sensor = zone_cfg.get(CONF_HVAC_AC_LOAD_SENSOR, "") or ""
                ac_ramp_zone_enabled = zone_cfg.get(
                    CONF_HVAC_AC_RAMP_ZONE_ENABLED,
                    DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED,
                )
                min_delta_f = _min_delta_from(zone_cfg)

                # If thermostat already assigned, merge rooms into existing zone
                existing_zone_id = thermostat_to_zone_id.get(thermostat)
                if existing_zone_id is not None:
                    existing = self._zones[existing_zone_id]
                    existing.rooms.extend(room_names)
                    existing.zone_name = f"{existing.zone_name} + {zm_zone_name}"
                    # Enable sweep if either zone wants it
                    existing.vacancy_sweep_enabled = (
                        existing.vacancy_sweep_enabled or sweep_enabled
                    )
                    # Merge zone_persons (deduplicated)
                    for p in zone_persons:
                        if p not in existing.zone_persons:
                            existing.zone_persons.append(p)
                    # Merge zone_cameras (deduplicated)
                    for c in zone_cameras:
                        if c not in existing.zone_cameras:
                            existing.zone_cameras.append(c)
                    # v4.5.11: prefer first non-empty ac_load_sensor; ramp-zone
                    # enabled if either zone wants it. (When two ZM zones share
                    # a thermostat, they share the same physical AC — same
                    # circuit on Span — so any non-empty sensor wins.)
                    if not existing.ac_load_sensor and ac_load_sensor:
                        existing.ac_load_sensor = ac_load_sensor
                    existing.ramp_zone_enabled = (
                        existing.ramp_zone_enabled or bool(ac_ramp_zone_enabled)
                    )
                    # W1-C P2: one physical thermostat — the wider gap wins
                    # (the field is mirrored, so they normally agree).
                    existing.thermostat_min_delta_f = max(
                        existing.thermostat_min_delta_f, min_delta_f,
                    )
                    _LOGGER.info(
                        "HVAC: Merged %s into %s (%s) — now %d rooms",
                        zm_zone_name, existing_zone_id,
                        thermostat, len(existing.rooms),
                    )
                    continue

                zone_id = self._zone_id_from_thermostat(
                    thermostat, next_zone_num
                )
                if zone_id == f"zone_{next_zone_num}":
                    next_zone_num += 1
                thermostat_to_zone_id[thermostat] = zone_id

                zone_state = ZoneState(
                    zone_id=zone_id,
                    zone_name=zm_zone_name,
                    climate_entity=thermostat,
                    rooms=room_names,
                    vacancy_sweep_enabled=sweep_enabled,
                    zone_persons=zone_persons,
                    zone_cameras=zone_cameras,
                    ac_load_sensor=ac_load_sensor,
                    ramp_zone_enabled=bool(ac_ramp_zone_enabled),
                    thermostat_min_delta_f=min_delta_f,
                )
                # Initialize never-occupied zones as eligible for vacancy
                zone_state.last_occupied_time = (
                    dt_util.utcnow()
                    - timedelta(minutes=DEFAULT_VACANCY_GRACE_MINUTES + 1)
                )
                self._zones[zone_id] = zone_state

                _LOGGER.info(
                    "HVAC: Discovered %s (%s) → %s (%d rooms, sweep=%s)",
                    zone_id, zm_zone_name, thermostat, len(room_names),
                    sweep_enabled,
                )

        # 2. Legacy fallback: individual ENTRY_TYPE_ZONE entries
        seen_thermostats: set[str] = set(thermostat_to_zone_id.keys())
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ZONE:
                continue

            merged = {**entry.data, **entry.options}
            thermostat = merged.get(CONF_ZONE_THERMOSTAT)
            if not thermostat:
                continue

            # Convert entry IDs to room names (same as Zone Manager path)
            raw_rooms = merged.get(CONF_ZONE_ROOMS, [])
            room_names = []
            if isinstance(raw_rooms, list):
                for r in raw_rooms:
                    room_names.append(entry_id_to_room_name.get(r, r))

            # Merge into existing zone if thermostat already assigned
            existing_zone_id = thermostat_to_zone_id.get(thermostat)
            if existing_zone_id is not None:
                existing = self._zones[existing_zone_id]
                existing.rooms.extend(room_names)
                continue

            if thermostat in seen_thermostats:
                continue

            seen_thermostats.add(thermostat)
            zone_id = self._zone_id_from_thermostat(
                thermostat, next_zone_num
            )
            if zone_id == f"zone_{next_zone_num}":
                next_zone_num += 1
            zone_name = merged.get("zone_name", f"Zone {zone_id.split('_')[-1]}")
            thermostat_to_zone_id[thermostat] = zone_id

            # v4.5.11: legacy fallback path also reads ramp-down fields,
            # to avoid Bug Class #33 (partial fix — sibling helper skipped).
            # Single-user URA installs don't use this path today, but
            # consistency matters if anyone ever migrates back.
            legacy_ac_load_sensor = merged.get(
                CONF_HVAC_AC_LOAD_SENSOR, ""
            ) or ""
            legacy_ramp_zone_enabled = merged.get(
                CONF_HVAC_AC_RAMP_ZONE_ENABLED,
                DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED,
            )

            zone_state = ZoneState(
                zone_id=zone_id,
                zone_name=zone_name,
                climate_entity=thermostat,
                rooms=room_names,
                ac_load_sensor=legacy_ac_load_sensor,
                ramp_zone_enabled=bool(legacy_ramp_zone_enabled),
                thermostat_min_delta_f=_min_delta_from(merged),
            )
            zone_state.last_occupied_time = (
                dt_util.utcnow()
                - timedelta(minutes=DEFAULT_VACANCY_GRACE_MINUTES + 1)
            )
            self._zones[zone_id] = zone_state

            _LOGGER.info(
                "HVAC: Discovered %s (%s) → %s (%d rooms)",
                zone_id, zone_name, thermostat,
                len(room_names),
            )

        _LOGGER.info("HVAC: Discovered %d zones with thermostats", len(self._zones))
        return len(self._zones)

    def update_zone_climate_state(self, zone_id: str) -> None:
        """Update zone state from its climate entity."""
        zone = self._zones.get(zone_id)
        if zone is None:
            return

        state = self.hass.states.get(zone.climate_entity)
        if state is None or state.state == "unavailable":
            return

        zone.hvac_mode = state.state
        zone.hvac_action = state.attributes.get("hvac_action", "")
        # W1-C P2 R1 (the hub): the thermostat profile's projection
        # (Carrier / Generic: the raw attribute verbatim).
        from .hvac_strategy import preset_of_for  # noqa: PLC0415
        zone.preset_mode = preset_of_for(self.hass, zone.climate_entity, state, "")
        zone.current_temperature = state.attributes.get("current_temperature")
        zone.current_humidity = state.attributes.get("current_humidity")
        zone.target_temp_high = state.attributes.get("target_temp_high")
        zone.target_temp_low = state.attributes.get("target_temp_low")

    def update_all_zones(self) -> None:
        """Update climate state for all zones."""
        for zone_id in self._zones:
            self.update_zone_climate_state(zone_id)

    def update_room_conditions(
        self,
        house_state: str | None = None,
        zone_ids: set[str] | None = None,
        entry_dwell_s: float | None = None,
        away_edge_fn: Any = None,
        return_window_s: float | None = None,
    ) -> None:
        """Aggregate room conditions per zone from URA room coordinators.

        Room coordinators are stored at hass.data[DOMAIN][entry.entry_id],
        keyed by config entry UUID. We find them by matching room_name
        from config entries against zone.rooms.

        HVAC-ZONE-CONDITIONING-DEMAND-1 D1 (2026-09-16): `house_state` is
        optional. When set to a member of `HVAC_NIGHT_HOLD_STATES` (sleep /
        waking — NOT home_night, HVAC-NIGHT-TAIL-STARTS-TOO-EARLY-1), the
        SHADOW per-room tail-hold selects from `ROOM_TYPE_HVAC_HOLD_NIGHT`;
        otherwise from the frozen `ROOM_TYPE_HVAC_TAIL_LEGACY`. None => day
        table (safe default for callers that haven't been threaded yet).

        HVAC fast occupancy response (v5.103.20, plan §4.2 / §5.3):
          * `zone_ids` — when set, ONLY those zones' room conditions are
            rebuilt (zone-scoped fast run); every other zone's
            `room_conditions` / rollup fields are left untouched. The filter
            is applied BEFORE `room_conditions.clear()`.
          * `_coordinator_absent_this_pass` is built in the ENTRY loop (for
            every room that belongs to any zone), so it is pass-complete
            whether or not the pass is zone-filtered.
          * Each room's HVAC evidence (`get_last_hvac_evidence_time`,
            `is_hvac_evidence_active`) and refresh health
            (`last_update_success`) are read here and handed to
            `_compute_hvac_occupied`, which runs the shadow machine AND the
            evidence rule and returns the state-selected output.
          * Back-fill: on a pass where a zone is fused-empty in an evidence
            or night state, `last_occupied_time` is raised to the exact
            release instant (max room release over ARMED rooms), so the
            vacancy grace counts from the release, not from the last pass
            that saw occupancy. Pending / never-armed episodes never touch it.
          * D5 (plan §5b): `entry_dwell_s` = knob 47 × 60 (W; None/0 = off)
            and `away_edge_fn(zone_id) -> bool` (the zone's last APPLIED S1
            write was `away` and it is not pre-arrival) are threaded to the
            evidence rule; the rollup fills `zone.hvac_pending_arm_rooms`.
        """
        # Build room_name -> coordinator mapping. v4.7.8 D3: also collect
        # CONF_WINDOW_SENSORS + CONF_IS_EGRESS_WINDOW per room so EgressManager
        # has fresh window state every tick without re-iterating config entries.
        from ..const import CONF_IS_EGRESS_WINDOW, DEFAULT_IS_EGRESS_WINDOW
        from ..const import CONF_WINDOW_SENSORS as _CONF_WINDOW_SENSORS

        # HVAC-ZONE-CONDITIONING-DEMAND-1 D1: read CONF_ROOM_TYPE so the
        # D1 producer can apply CIRCULATION EXCLUSION for hallways.
        # HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 D1/D2 (v5.103.8): read the
        # per-room CONF_HVAC_VACANCY_HOLD[_NIGHT] optional overrides
        # (reintroduced with a real ROOM options-flow UI) and stash them
        # on the room's meta so `_compute_hvac_occupied` can pass them
        # into the resolver. Zero room-name literals — everything keys
        # on room_type + optional per-entry overrides.
        from ..const import (
            CONF_ROOM_TYPE,
            CONF_HVAC_VACANCY_HOLD,
            CONF_HVAC_VACANCY_HOLD_NIGHT,
            CONF_HVAC_SKIP_ENTRY_WAIT,
            DEFAULT_HVAC_SKIP_ENTRY_WAIT,
            ROOM_TYPE_GENERIC,
            ROOM_TYPE_HALLWAY,
        )

        room_coordinators: dict[str, Any] = {}
        room_entry_meta: dict[str, dict[str, Any]] = {}
        # HVAC-DEGRADED-ROOM-TRIPWIRE-1 REV-2 F6: rebuild reverse map every
        # pass so `_classify_all_rooms` can read entry.state / .disabled_by.
        self._room_entry_by_name = {}
        # REV-2 F4: pass-scoped set — rebuilt here, consulted by REV-2 D2
        # step 4. v5.103.20 (plan §5.3, REV 2 R2 M6): populated in THIS
        # entry loop for every zone room whose coordinator is absent, so a
        # zone-filtered pass still yields a pass-complete set.
        # REV-2 fix-up item 5: pre-compute rooms-in-any-zone (moved ahead of
        # the entry loop for the pass-complete absent set; the classifier
        # below still reads it).
        rooms_in_zones: set[str] = set()
        for _z in self._zones.values():
            for _r in getattr(_z, "rooms", []) or []:
                rooms_in_zones.add(_r)
        # v5.103.20 fix-up 1 (B-M3): on a ZONE-FILTERED pass only the
        # filtered zones' rooms are re-evaluated for coordinator absence
        # and classification; every other room KEEPS its previous value.
        _filtered_rooms: set[str] | None = None
        if zone_ids is not None:
            _filtered_rooms = set()
            for _z in self._zones.values():
                if _z.zone_id in zone_ids:
                    _filtered_rooms.update(getattr(_z, "rooms", []) or [])
            _prev_absent = set(self._coordinator_absent_this_pass)
            self._coordinator_absent_this_pass = {
                r for r in _prev_absent if r not in _filtered_rooms
            }
        else:
            self._coordinator_absent_this_pass = set()
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ROOM:
                continue
            room_name = entry.data.get(CONF_ROOM_NAME, "")
            if not room_name:
                continue
            self._room_entry_by_name[room_name] = entry
            coordinator = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if coordinator is not None:
                room_coordinators[room_name] = coordinator
            elif room_name in rooms_in_zones and (
                _filtered_rooms is None or room_name in _filtered_rooms
            ):
                self._coordinator_absent_this_pass.add(room_name)
            merged = {**entry.data, **entry.options}
            _ws = merged.get(_CONF_WINDOW_SENSORS) or None
            # v4.7.8 fix-up C-L4: only treat as egress when a window_sensor
            # is configured. Otherwise the room can't ever observe an open
            # window — defaulting True is meaningless cosmetic context.
            _is_egress = bool(merged.get(
                CONF_IS_EGRESS_WINDOW, DEFAULT_IS_EGRESS_WINDOW,
            )) and bool(_ws)
            room_entry_meta[room_name] = {
                "entry_id": entry.entry_id,
                "window_sensor": _ws,
                # Lazy default per v4.7.4.4 Bug Class #46 doctrine.
                "is_egress_window": _is_egress,
                "room_type": (
                    merged.get(CONF_ROOM_TYPE, ROOM_TYPE_GENERIC)
                    or ROOM_TYPE_GENERIC
                ),
                # HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 D1/D2: optional
                # per-room hold overrides (blank/None -> table default).
                # Coerce numeric strings; sentinel non-int as None.
                "hvac_hold_override_day": _coerce_hold_override(
                    merged.get(CONF_HVAC_VACANCY_HOLD, None)
                ),
                "hvac_hold_override_night": _coerce_hold_override(
                    merged.get(CONF_HVAC_VACANCY_HOLD_NIGHT, None)
                ),
                # v5.103.20 fix-up 1 (ruling 3): per-room "Skip entry wait".
                "hvac_skip_entry_wait": bool(
                    merged.get(CONF_HVAC_SKIP_ENTRY_WAIT, DEFAULT_HVAC_SKIP_ENTRY_WAIT)
                ),
            }

        # v4.7.8 fix-up B-M1 / B4: unify on dt_util.now() (URA-wide convention)
        # — egress module uses dt_util.now(); cross-module split was fragile.
        now = dt_util.now()
        # HVAC-DEGRADED-ROOM-TRIPWIRE-1 (2026-09-26): classify every ROOM
        # entry once per pass BEFORE the per-zone loop so the sync
        # `is_zone_hvac_established` gate can read a coherent snapshot.
        # REV-2 fix-up item 6: grace-window clock is UTC (dt_util.utcnow())
        # — DST-safe. Local `now` above is kept for the tail machinery.
        # REV-2 fix-up item 5: classifier only emits WARN+NM for rooms that
        # actually belong to an HVAC zone (`rooms_in_zones` built above).
        self._rooms_in_any_zone = rooms_in_zones
        self._classify_all_rooms(dt_util.utcnow(), only_rooms=_filtered_rooms)
        # v5.103.20: pass-complete snapshots for the sync release helpers.
        # On a filtered pass merge over the previous snapshot so other
        # zones' rooms keep resolving (B-M3).
        if _filtered_rooms is None:
            self._room_meta_last_pass = room_entry_meta
            self._room_coord_last_pass = room_coordinators
        else:
            self._room_meta_last_pass = {**self._room_meta_last_pass, **room_entry_meta}
            self._room_coord_last_pass = {**self._room_coord_last_pass, **room_coordinators}
        self._last_house_state = house_state
        try:
            _RW = float(return_window_s) if return_window_s is not None else None
        except (TypeError, ValueError):
            _RW = None
        if _RW is None:
            from .hvac_const import DEFAULT_HVAC_RETURN_WINDOW_MINUTES as _DRW  # noqa: PLC0415
            _RW = float(_DRW) * 60.0
        self._last_return_window_s = _RW
        self._rooms_processed_this_pass = set()
        from .hvac_const import (  # noqa: PLC0415
            HVAC_EVIDENCE_RULE_STATES as _EV_STATES,
            HVAC_NIGHT_HOLD_STATES as _NIGHT_STATES,
        )
        _backfill_states = house_state in _EV_STATES or house_state in _NIGHT_STATES
        try:
            _W = float(entry_dwell_s or 0.0)
        except (TypeError, ValueError):
            _W = 0.0
        for zone in self._zones.values():
            # v5.103.20 (plan §5.3): zone filter BEFORE clear() — a
            # zone-scoped fast run must leave sibling zones' conditions,
            # rollup fields and shadow state untouched.
            if zone_ids is not None and zone.zone_id not in zone_ids:
                continue
            # D5: the zone's away edge, read ONCE per zone per pass (only
            # meaningful in evidence states with the filter on).
            _away_edge = False
            if _W > 0 and house_state in _EV_STATES and callable(away_edge_fn):
                try:
                    _away_edge = bool(away_edge_fn(zone.zone_id))
                except Exception:  # noqa: BLE001 — unknown edge = False (fail open)
                    _away_edge = False
            zone.room_conditions.clear()
            for room_name in zone.rooms:
                coordinator = room_coordinators.get(room_name)
                meta = room_entry_meta.get(room_name, {})
                window_sensor = meta.get("window_sensor")
                window_state: str | None = None
                if window_sensor:
                    try:
                        st = self.hass.states.get(window_sensor)
                        if st is not None:
                            window_state = st.state
                    except Exception:
                        window_state = None

                if coordinator is None:
                    # v5.103.20 fix-up 1 (D-M1): a room without a coordinator
                    # (unloading / deleted) can neither pend nor hold.
                    self._clear_episode(room_name)
                    self._hvac_pending[room_name] = False
                    self._hvac_cold[room_name] = False
                    self._hvac_exempt_reason[room_name] = None
                    # HVAC-DEGRADED-ROOM-TRIPWIRE-1 REV-2 F4: the room was
                    # marked coordinator-absent in the ENTRY loop above
                    # (v5.103.20 moved the add so a zone-filtered pass is
                    # still pass-complete). REV-2 D2 step 4 blocks
                    # establishment on any live room absent on the latest
                    # pass — belt (entry state = LOADED) + braces
                    # (coordinator actually there).
                    # v4.7.8 fix-up A-H1 (Bug Class #43): if the room entry
                    # exists but its coordinator hasn't booted yet, STILL
                    # append a RoomCondition populated from entry meta so
                    # EgressManager sees the egress-window state on the first
                    # tick post-restart. Without this, a paused zone whose
                    # only egress room's coordinator is briefly absent will
                    # silently see any_egress_open=False and resume
                    # prematurely. Other rules already tolerate occupied=False.
                    if meta:
                        # D1: on missing coordinator, hvac_occupied stays False
                        # (matches lighting-fused .occupied). No arm attempted.
                        zone.room_conditions.append(RoomCondition(
                            room_name=room_name,
                            temperature=None,
                            humidity=None,
                            occupied=False,
                            hvac_occupied=False,
                            window_sensor=window_sensor,
                            window_state=window_state,
                            is_egress_window=bool(meta.get(
                                "is_egress_window", True,
                            )),
                            room_entry_id=meta.get("entry_id"),
                        ))
                    continue

                # Read from room coordinator data dict
                data = {}
                if hasattr(coordinator, "data") and coordinator.data:
                    data = coordinator.data
                room_occupied = bool(data.get("occupied", False))

                # HVAC-ZONE-CONDITIONING-DEMAND-1 D1: per-room state machine.
                # `hvac_occupied` rides grace-held STATE_OCCUPIED + tail-hold,
                # with hallway rooms unconditionally excluded (CIRCULATION
                # EXCLUSION — CRIT-1 closure: kind is not read on this path).
                room_type = str(meta.get("room_type", ROOM_TYPE_GENERIC))
                if room_type == ROOM_TYPE_HALLWAY:
                    hvac_occupied_val = False
                    self._hvac_armed[room_name] = False
                    self._hvac_tail_until.pop(room_name, None)
                    self._hvac_arm_source[room_name] = "hallway_excluded"
                    # v5.103.20 fix-up 1 (D-M1): a room retyped to hallway
                    # drops any D5 episode / pending state.
                    self._clear_episode(room_name)
                    self._hvac_pending[room_name] = False
                    self._hvac_cold[room_name] = False
                    self._hvac_exempt_reason[room_name] = None
                    self._hvac_output[room_name] = False
                    # D-HIGH-1: hallway rooms are still "seen" — their
                    # coordinator is live; the state machine just short-
                    # circuits them via CIRCULATION EXCLUSION. Marking
                    # them seen means a zone consisting solely of
                    # hallway + dwelling rooms can still reach
                    # ESTABLISHED once the dwelling room is read.
                    self._hvac_seen.add(room_name)
                else:
                    # v5.103.20 (plan §4.2): read the room's HVAC evidence
                    # defensively — `isinstance(ev, datetime)` (a MagicMock
                    # or a legacy fake yields None), `is True` for the
                    # active flag, and `last_update_success is not False`
                    # for refresh health.
                    last_evidence, evidence_active, onset, refresh_ok = (
                        self._read_room_evidence(coordinator)
                    )
                    hvac_occupied_val = self._compute_hvac_occupied(
                        room_name=room_name,
                        room_type=room_type,
                        state_occupied=room_occupied,
                        now=now,
                        house_state=house_state,
                        override_day=meta.get("hvac_hold_override_day"),
                        override_night=meta.get("hvac_hold_override_night"),
                        last_evidence=last_evidence,
                        evidence_active=evidence_active,
                        refresh_ok=refresh_ok,
                        onset=onset,
                        entry_dwell_s=_W,
                        away_edge=_away_edge,
                        zone_id=zone.zone_id,
                        return_window_s=_RW,
                        skip_entry_wait=bool(meta.get("hvac_skip_entry_wait", False)),
                        # The producer path ALWAYS applies the rule (a room
                        # with no evidence yet is simply not held in an
                        # evidence state); only direct legacy callers get
                        # the shadow by default.
                        apply_evidence_rule=True,
                    )

                self._rooms_processed_this_pass.add(room_name)
                condition = RoomCondition(
                    room_name=room_name,
                    temperature=data.get("temperature"),
                    humidity=data.get("humidity"),
                    occupied=room_occupied,
                    hvac_occupied=hvac_occupied_val,
                    window_sensor=window_sensor,
                    window_state=window_state,
                    is_egress_window=bool(meta.get("is_egress_window", True)),
                    room_entry_id=meta.get("entry_id"),
                )
                zone.room_conditions.append(condition)

            # v3.17.0 D1: Track last_occupied_time for vacancy management.
            # HVAC-ZONE-CONDITIONING-DEMAND-1 §2a: write basis now split by
            # denomination. `last_occupied_time` + `continuous_occupied_since`
            # feed HVAC-decision code (preset flip grace + stale-occupancy
            # failsafe), so their write basis SWAPS to the HVAC denomination
            # (rows 2a + 2c). `vacancy_sweep_done` (lighting actuator, row 2b)
            # and `current_session_start` (row 2d, lighting-timing flap guard
            # inside `_zone_entry_dwell`) STAY on the lighting-fused
            # `any_room_occupied` — swapping them would leave hallway lights
            # on / neuter the lighting-flap guard. Row 2e = mirror each
            # write's verdict; split the single if/else into two guards.
            if zone.any_room_hvac_occupied:
                # Row 2a: HVAC-denomination write source.
                zone.last_occupied_time = now
                # Row 2c: HVAC-denomination write source.
                if zone.continuous_occupied_since is None:
                    zone.continuous_occupied_since = now
            else:
                # Row 2c reset: mirrors write source above.
                # HVAC W1/W2 finish C3 (INV-C, W2-2 ruling Q5): a zone with a
                # TRANSIENT (reloading) room reads a synthetic "empty" for
                # that room, so the stuck-occupancy failsafe's clock is NOT
                # reset on such a pass. Guards ONLY this assignment — the
                # back-fill below stays unconditional (M4). Rooms are
                # classified EARLIER in this same call (`_classify_all_rooms`),
                # so the guard already applies on the first pass after a
                # restart (a restored clock survives while rooms load). It
                # discharges when the room is LOADED or excluded
                # (transient >= 300 s).
                if not self.is_zone_transient_blocked(zone.zone_id):
                    zone.continuous_occupied_since = None
                # v5.103.20 (plan §4.5, INV-2): back-fill the exact release
                # instant — evidence and night states ONLY (legacy states
                # keep v5.103.19 byte-for-byte). `last_occupied_time` is the
                # grace clock's anchor; without this the grace would count
                # from the last PASS that saw the zone occupied (up to one
                # tick early) and the fast exit could fire before hold + G.
                if _backfill_states:
                    _e = self._zone_release_bound(zone, now, house_state)
                    if _e is not None and (
                        zone.last_occupied_time is None
                        or _e > zone.last_occupied_time
                    ):
                        zone.last_occupied_time = _e

            # D5 rollup (plan §4.2 step 6): the zone's pending rooms. Only
            # meaningful in evidence states; empty otherwise.
            # v5.103.20 fix-up 1 (D-M1): only rooms that are LIVE on this
            # pass (coordinator present, not hallway, classified live) can
            # be pending — a disabled / deleted / retyped room drops out.
            zone.hvac_pending_arm_rooms = [
                r for r in zone.rooms
                if self._hvac_pending.get(r, False)
                and r in self._rooms_processed_this_pass
                and self._room_hvac_class.get(r, ("live", ""))[0] == "live"
            ]

            # Row 2b: lighting-fused vacancy_sweep_done reset (NO-SWAP).
            # Row 2d: lighting-fused session_start (NO-SWAP).
            if zone.any_room_occupied:
                zone.vacancy_sweep_done = False  # Row 2b
                if zone.current_session_start is None:
                    zone.current_session_start = now  # Row 2d
            else:
                zone.current_session_start = None  # Row 2d reset

    def get_zone_status_attrs(
        self,
        zone_id: str,
        window_seconds: int | None = None,
        away_grace_s: float | None = None,
    ) -> dict[str, Any]:
        """Return rich attribute dict for a zone status sensor.

        `away_grace_s` (HVAC-PUBLISH-ZONE-AWAY-DUE-AND-ARRESTER-TIMERS-1):
        the LIVE vacancy grace the HVAC coordinator uses now
        (`HVACCoordinator._exit_grace_seconds`). When None, `away_due_at`
        is published as None. Display only.

        B-M2 (fix-up) — duty_cycle_pct denominator honors the LIVE window
        knob when the caller passes it; falls back to the module constant
        when None (preserves pre-fix behavior for callers that lack a
        coordinator handle).
        """
        zone = self._zones.get(zone_id)
        if zone is None:
            return {}
        _win_sec = int(window_seconds) if window_seconds and window_seconds > 0 else DUTY_CYCLE_WINDOW_SECONDS

        return {
            "friendly_name": zone.zone_name,
            "zone_id": zone.zone_id,
            "climate_entity": zone.climate_entity,
            # W1-C P2 D1: which thermostat adapter commands this zone.
            **_profile_attrs(self.hass, zone.climate_entity),
            "preset_mode": zone.preset_mode,
            "hvac_action": zone.hvac_action,
            "current_temperature": zone.current_temperature,
            "current_humidity": zone.current_humidity,
            "target_temp_high": zone.target_temp_high,
            "target_temp_low": zone.target_temp_low,
            "any_room_occupied": zone.any_room_occupied,
            # HVAC-ZONE-CONDITIONING-DEMAND-1 D1: expose HVAC-denomination
            # sibling on the zone status attrs so D7/D9 observers and the
            # per-zone diagnostic surface can read the fused signal.
            "any_room_hvac_occupied": zone.any_room_hvac_occupied,
            # v5.103.20 (plan §3.2 zone-status row): exact release + D5 exposure.
            "hvac_empty_since": (
                zone.last_occupied_time.isoformat()
                if (not zone.any_room_hvac_occupied and zone.last_occupied_time is not None)
                else None
            ),
            "hvac_release_at": (
                self.zone_release_at(zone_id).isoformat()
                if self.zone_release_at(zone_id) is not None else None
            ),
            "away_due_at": self._away_due_at_attr(zone, away_grace_s),
            "pending_arm_rooms": list(getattr(zone, "hvac_pending_arm_rooms", []) or []),
            # fix-up 1 (A-LOW-5): the CURRENT spell accrues live, not only
            # once it closes.
            "pending_hold_s_today": int(
                (getattr(zone, "pending_hold_s_today", 0.0) or 0.0)
                + (
                    max(0.0, (dt_util.utcnow() - zone.pending_hold_since).total_seconds())
                    if getattr(zone, "pending_hold_since", None) is not None else 0.0
                )
            ),
            "transit_filtered_today": int(self.transit_filtered_today.get(zone_id, 0)),
            # HVAC-DEGRADED-ROOM-TRIPWIRE-1 REV-2 D3/F1 (2026-09-26):
            # live-room classification for this zone. `excluded_rooms`
            # / `transient_rooms` include the reason for operator diag
            # visibility. `transient_rooms` also reports seconds-non-
            # loaded so a stuck reload is directly observable.
            # FIX-UP item 7: wrap each of the four live-room diag keys
            # in try/except returning [] so a poisoned classifier / naive
            # datetime never breaks the zone status sensor.
            "live_rooms": self._safe_diag_live_rooms(zone),
            "excluded_rooms": self._safe_diag_excluded_rooms(zone),
            "transient_rooms": self._safe_diag_transient_rooms(zone),
            "coordinator_absent_rooms": self._safe_diag_coord_absent_rooms(zone),
            "occupied_rooms": zone.occupied_rooms,
            "avg_temperature": (
                round(zone.avg_temperature, 1)
                if zone.avg_temperature is not None
                else None
            ),
            "avg_humidity": (
                round(zone.avg_humidity, 1)
                if zone.avg_humidity is not None
                else None
            ),
            "room_count": len(zone.rooms),
            "override_count_today": zone.override_count_today,
            "ac_reset_count_today": zone.ac_reset_count_today,
            "zone_persons": zone.zone_persons,
            "zone_cameras": zone.zone_cameras,
            "camera_face_arrivals_today": zone.camera_face_arrivals_today,
            # v3.17.0: Zone Intelligence attributes
            "zone_presence_state": zone.zone_presence_state,
            "vacancy_sweep_done": zone.vacancy_sweep_done,
            "vacancy_sweep_enabled": zone.vacancy_sweep_enabled,
            # HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1 (D-b1): renamed
            # operator-facing attribute from `runtime_exceeded` to
            # `energy_shed_cap_reached`. Internal field name kept for
            # serialization/restore stability. No alias per
            # Single-User-No-Back-Compat.
            "energy_shed_cap_reached": zone.runtime_exceeded,
            # F2 (fix-up round) — display-compat shim. The pre-built
            # frontend-v3 bundle (assets/HVAC-*.js + Zones-*.js) keys
            # its yellow duty-cap card on `attrs.runtime_exceeded`; the
            # rebuild has NOT been run in this fix-up round (dashboard-v3
            # source updated but not compiled). Dual-emit the display
            # attribute so the shipping bundle keeps rendering. This is
            # a DISPLAY-ONLY shim — the reason-ladder string is NOT
            # dual-emitted (F1 completed the rename in the reason
            # surface). Retire once the frontend bundle is rebuilt from
            # the updated dashboard-v3 source.
            "runtime_exceeded": zone.runtime_exceeded,
            "runtime_duty_cycle_pct": (
                min(
                    round(
                        zone.runtime_seconds_this_window
                        / _win_sec
                        * 100,
                        1,
                    ),
                    100.0,
                )
                if zone.window_start is not None
                else 0.0
            ),
            "continuous_occupied_hours": (
                round(
                    (dt_util.utcnow() - zone.continuous_occupied_since).total_seconds()
                    / 3600,
                    1,
                )
                if zone.continuous_occupied_since is not None
                else 0.0
            ),
        }

    def get_state_snapshot(self) -> dict[str, dict]:
        """Serialize zone state for persistence.

        v3.18.2: Returns a dict of zone_id -> state dict for storage.
        """
        snapshot = {}
        for zone_id, zone in self.zones.items():
            snapshot[zone_id] = {
                "last_occupied_time": zone.last_occupied_time.isoformat() if zone.last_occupied_time else None,
                "vacancy_sweep_done": zone.vacancy_sweep_done,
                "zone_presence_state": zone.zone_presence_state,
                "continuous_occupied_since": zone.continuous_occupied_since.isoformat() if zone.continuous_occupied_since else None,
                "runtime_seconds_this_window": zone.runtime_seconds_this_window,
                "window_start": zone.window_start.isoformat() if zone.window_start else None,
                "zone_persons": zone.zone_persons,
                "saved_at": dt_util.now().isoformat(),
            }
        return snapshot

    def restore_state_snapshot(self, snapshot: dict[str, dict]) -> int:
        """Restore zone state from persisted snapshot.

        v3.18.2: Applies persisted state to matching zones.
        Skips stale data (>4h old). Returns count of restored zones.
        """
        restored = 0
        now = dt_util.now()
        for zone_id, state in snapshot.items():
            zone = self.zones.get(zone_id)
            if zone is None:
                continue

            # Skip stale data (>4h old)
            # v3.18.x review fix: Use dt_util.parse_datetime for TZ safety
            saved_at_str = state.get("saved_at")
            if saved_at_str:
                try:
                    saved_at = dt_util.parse_datetime(saved_at_str) or dt_util.now()
                    if (now - saved_at).total_seconds() > 4 * 3600:
                        _LOGGER.info("HVAC Zones: Skipping stale state for zone %s (saved %s)", zone_id, saved_at_str)
                        continue
                except (ValueError, TypeError):
                    continue

            # Restore fields
            # v3.18.x review fix: Use dt_util.parse_datetime for TZ-safe parsing
            lot = state.get("last_occupied_time")
            if lot:
                parsed = dt_util.parse_datetime(lot)
                if parsed is not None:
                    zone.last_occupied_time = parsed

            zone.vacancy_sweep_done = state.get("vacancy_sweep_done", False)
            zone.zone_presence_state = state.get("zone_presence_state", "unknown")

            cos = state.get("continuous_occupied_since")
            if cos:
                parsed = dt_util.parse_datetime(cos)
                if parsed is not None:
                    zone.continuous_occupied_since = parsed

            zone.runtime_seconds_this_window = state.get("runtime_seconds_this_window", 0.0)
            # Note: zone_persons is NOT restored from snapshot — config entry is
            # the source of truth for person assignments (set via config flow).
            # Restoring from snapshot would overwrite fresh config data on restart.

            ws = state.get("window_start")
            if ws:
                parsed = dt_util.parse_datetime(ws)
                if parsed is not None:
                    zone.window_start = parsed

            restored += 1
            _LOGGER.info("HVAC Zones: Restored state for zone %s (presence=%s)", zone_id, zone.zone_presence_state)

        return restored

    # ------------------------------------------------------------------
    # HVAC-ZONE-CONDITIONING-DEMAND-1 D1 producer helpers
    # ------------------------------------------------------------------
    def _effective_hvac_hold_seconds(
        self,
        room_type: str,
        house_state: str | None,
        override_day: int | None = None,
        override_night: int | None = None,
        room_name: str | None = None,
    ) -> int:
        """Return the SHADOW tail-hold window for a room in seconds.

        v5.103.20 (HVAC fast occupancy response, plan §4.4): this is the
        shadow machine's selector. Its day value now comes from the FROZEN
        `ROOM_TYPE_HVAC_TAIL_LEGACY` (v5.103.19 values), NOT from
        `ROOM_TYPE_HVAC_HOLD` (the evidence-rule table, `_evidence_hold_seconds`).
        Logic, signature, overrides and the numeric clamp are unchanged, so
        the shadow runs byte-for-byte as v5.103.19 (INV-5) and the clamp still
        compares night against the legacy day value (common night 90 >= 60:
        no lift). Callers: `_compute_hvac_occupied` (shadow), `_display_hold`.

        Selects day vs night table by `house_state in HVAC_NIGHT_HOLD_STATES`
        (sleep / waking; HVAC-NIGHT-TAIL-STARTS-TOO-EARLY-1, 2026-09-27 —
        home_night deliberately uses the DAY value).
        HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 D1/D2 (v5.103.8): honour the
        optional per-room `override_day` / `override_night` (from the
        ROOM options-flow CONF_HVAC_VACANCY_HOLD[_NIGHT] fields). None
        means "no override" — fall through to the module-constant
        table. Monotonicity clamp: if BOTH overrides are supplied AND
        the night override is smaller than the (resolved) day value,
        clamp night up to day and log ONCE per (room_type, house_state)
        so the operator sees the intent violation without a firehose.
        """
        from ..const import (
            ROOM_TYPE_HVAC_TAIL_LEGACY,
            ROOM_TYPE_HVAC_HOLD_NIGHT,
            DEFAULT_HVAC_VACANCY_HOLD,
            DEFAULT_HVAC_VACANCY_HOLD_NIGHT,
        )
        from .hvac_const import HVAC_NIGHT_HOLD_STATES

        # Resolve day + night with overrides first (needed for clamp).
        day_val: int
        night_val: int
        try:
            day_val = int(ROOM_TYPE_HVAC_TAIL_LEGACY.get(
                room_type, DEFAULT_HVAC_VACANCY_HOLD,
            ))
        except (TypeError, ValueError):
            day_val = int(DEFAULT_HVAC_VACANCY_HOLD)
        try:
            night_val = int(ROOM_TYPE_HVAC_HOLD_NIGHT.get(
                room_type, DEFAULT_HVAC_VACANCY_HOLD_NIGHT,
            ))
        except (TypeError, ValueError):
            night_val = int(DEFAULT_HVAC_VACANCY_HOLD_NIGHT)
        if override_day is not None:
            day_val = int(override_day)
        if override_night is not None:
            night_val = int(override_night)

        # Monotonicity clamp: night MUST be >= day. Log-once key names
        # the specific ROOM (A-LOW-7 fixup, v5.103.8) — a room_type
        # key would collapse two inverted bedrooms into a single log
        # and hide one of them.
        if night_val < day_val:
            clamp_key = (room_name or "?", room_type, "night_lt_day")
            logged = getattr(self, "_hvac_hold_clamp_logged", None)
            if logged is None:
                logged = set()
                self._hvac_hold_clamp_logged = logged
            if clamp_key not in logged:
                _LOGGER.warning(
                    "HVAC hold monotonicity: room=%s (type=%s) "
                    "night=%ds < day=%ds — clamping night up to %ds "
                    "(overrides: day=%s night=%s)",
                    room_name or "?", room_type,
                    night_val, day_val, day_val,
                    override_day, override_night,
                )
                logged.add(clamp_key)
            night_val = day_val

        return night_val if house_state in HVAC_NIGHT_HOLD_STATES else day_val

    # ------------------------------------------------------------------
    # HVAC fast occupancy response (v5.103.20) — evidence-rule selectors
    # ------------------------------------------------------------------
    def _evidence_hold_seconds(
        self, room_type: str, override_day: int | None = None,
    ) -> int:
        """Evidence-rule hold (plan §4.4): the per-room DAY override if set,
        else `ROOM_TYPE_HVAC_HOLD[room_type]`, else DEFAULT_HVAC_VACANCY_HOLD.
        Counted from the room's LAST EVIDENCE (not the lighting timeout).
        Callers: the evidence term in `_compute_hvac_occupied`,
        `_room_release_from`, `_display_hold`."""
        from ..const import ROOM_TYPE_HVAC_HOLD, DEFAULT_HVAC_VACANCY_HOLD
        if override_day is not None:
            try:
                return max(0, int(override_day))
            except (TypeError, ValueError):
                pass
        try:
            return max(0, int(ROOM_TYPE_HVAC_HOLD.get(
                room_type, DEFAULT_HVAC_VACANCY_HOLD,
            )))
        except (TypeError, ValueError):
            return int(DEFAULT_HVAC_VACANCY_HOLD)

    @staticmethod
    def _hvac_rule_for_state(house_state: str | None) -> str:
        """`evidence` (home_day / home_evening), `night` (sleep / waking),
        else `legacy`."""
        from .hvac_const import HVAC_EVIDENCE_RULE_STATES, HVAC_NIGHT_HOLD_STATES
        if house_state in HVAC_EVIDENCE_RULE_STATES:
            return "evidence"
        if house_state in HVAC_NIGHT_HOLD_STATES:
            return "night"
        return "legacy"

    def _display_hold(
        self,
        room_type: str,
        house_state: str | None,
        override_day: int | None = None,
        override_night: int | None = None,
        room_name: str | None = None,
    ) -> tuple[int, str]:
        """(hold_seconds, rule) of the ACTIVE rule for the per-room diagnostic
        entity (plan §4.4 / §4.6 display rule): the evidence hold in evidence
        states, the night value in night states, the legacy tail otherwise."""
        rule = self._hvac_rule_for_state(house_state)
        if rule == "evidence":
            return self._evidence_hold_seconds(room_type, override_day), rule
        return (
            self._effective_hvac_hold_seconds(
                room_type, house_state,
                override_day=override_day, override_night=override_night,
                room_name=room_name,
            ),
            rule,
        )

    def _compute_hvac_occupied(
        self,
        *,
        room_name: str,
        room_type: str,
        state_occupied: bool,
        now: datetime,
        house_state: str | None,
        override_day: int | None = None,
        override_night: int | None = None,
        last_evidence: datetime | None = None,
        evidence_active: bool = False,
        refresh_ok: bool = True,
        apply_evidence_rule: bool | None = None,
        onset: datetime | None = None,
        entry_dwell_s: float = 0.0,
        away_edge: bool = False,
        zone_id: str | None = None,
        return_window_s: float | None = None,
        skip_entry_wait: bool = False,
    ) -> bool:
        """D1 producer — returns True iff the room is HVAC-occupied.

        v5.103.20 (plan §4.2). Two layers, one output:
          1. SHADOW: today's v5.103.19 machine (`_shadow_hvac_occupied`)
             runs byte-for-byte on `state_occupied` on EVERY pass in EVERY
             house state, and alone owns `_hvac_armed` /
             `_hvac_prev_state_occupied` / `_hvac_tail_until` /
             `_hvac_arm_source` (INV-5).
          2. EVIDENCE RULE (`_evidence_rule_output`): `active OR now <
             last_evidence + hold_ev`, bounded refresh-failure hold.
        Output by house state: evidence states -> rule; night states ->
        shadow OR rule; legacy states -> shadow.

        `apply_evidence_rule` defaults to "only when the caller supplied
        evidence" — `update_room_conditions` always does; a direct caller
        that passes no evidence keywords (pre-v5.103.20 tests, diagnostics)
        gets the shadow's output unchanged. Hallway is filtered upstream.
        """
        if apply_evidence_rule is None:
            apply_evidence_rule = (
                last_evidence is not None
                or evidence_active is not False
                or refresh_ok is not True
            )
        # Snapshot the shadow's release inputs BEFORE it runs, so the
        # release instant can be recorded without touching its dicts.
        _tail_before = self._hvac_tail_until.get(room_name)
        _armed_before = bool(self._hvac_armed.get(room_name, False))
        shadow_out = self._shadow_hvac_occupied(
            room_name=room_name,
            room_type=room_type,
            state_occupied=state_occupied,
            now=now,
            house_state=house_state,
            override_day=override_day,
            override_night=override_night,
        )
        if shadow_out:
            self._hvac_shadow_release_at.pop(room_name, None)
        elif _tail_before is not None:
            self._hvac_shadow_release_at[room_name] = _tail_before
        elif _armed_before:
            # released_no_tail (hold 0) — released at this pass.
            self._hvac_shadow_release_at[room_name] = now
        if not apply_evidence_rule:
            self._hvac_rule[room_name] = "legacy"
            self._hvac_output[room_name] = bool(shadow_out)
            return bool(shadow_out)
        return self._evidence_rule_output(
            room_name=room_name,
            room_type=room_type,
            now=now,
            house_state=house_state,
            override_day=override_day,
            last_evidence=last_evidence,
            evidence_active=evidence_active,
            refresh_ok=refresh_ok,
            shadow_out=bool(shadow_out),
            onset=onset,
            entry_dwell_s=entry_dwell_s,
            away_edge=away_edge,
            zone_id=zone_id,
            return_window_s=return_window_s,
            skip_entry_wait=skip_entry_wait,
        )

    def _evidence_rule_output(
        self,
        *,
        room_name: str,
        room_type: str,
        now: datetime,
        house_state: str | None,
        override_day: int | None,
        last_evidence: datetime | None,
        evidence_active: bool,
        refresh_ok: bool,
        shadow_out: bool,
        onset: datetime | None = None,
        entry_dwell_s: float = 0.0,
        away_edge: bool = False,
        zone_id: str | None = None,
        return_window_s: float | None = None,
        skip_entry_wait: bool = False,
    ) -> bool:
        """Evidence rule (plan §4.2 steps 2-5) + D5 (§5b). NEVER writes the
        shadow's dicts; writes only the evidence rule's own state.

        Refresh failure (`refresh_ok is False`): the room coordinator's stamp
        did not run, so the stale `evidence_active` is NOT trusted (else a
        dead coordinator would hold its zone forever). In evidence states the
        previous True output is held for at most
        HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S after `last_evidence`; in night /
        legacy states the shadow decides on stale data, as before.
        """
        from datetime import timedelta as _td
        from .hvac_const import HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S

        rule = self._hvac_rule_for_state(house_state)
        self._hvac_last_ev[room_name] = last_evidence
        self._hvac_last_active[room_name] = bool(evidence_active)
        if rule == "legacy":
            self._hvac_rule[room_name] = rule
            self._hvac_day_release_at.pop(room_name, None)
            self._hvac_output[room_name] = shadow_out
            # No D5, no pending hold in legacy states (INV-5). Per-pass
            # D5 fields are RESET so nothing stale survives (A-LOW-1/2).
            self._clear_episode(room_name)
            self._hvac_pending[room_name] = False
            self._hvac_cold[room_name] = False
            self._hvac_exempt_reason[room_name] = None
            self._hvac_arm_onset.pop(room_name, None)
            if shadow_out:
                self._hvac_ep_armed[room_name] = True
            return shadow_out

        prev_out = bool(self._hvac_output.get(room_name, False))
        hold_ev = self._evidence_hold_seconds(room_type, override_day)
        ev_release: datetime | None = None
        if last_evidence is not None:
            ev_release = last_evidence + _td(seconds=hold_ev)
            self._hvac_day_release_at[room_name] = ev_release
        else:
            self._hvac_day_release_at.pop(room_name, None)

        active = bool(evidence_active) if refresh_ok is not False else False
        ev_out = active or (ev_release is not None and now < ev_release)
        if (
            rule == "evidence"
            and refresh_ok is False
            and prev_out
            and not ev_out
            and last_evidence is not None
            and HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S > 0
            and now < last_evidence + _td(seconds=HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S)
        ):
            ev_out = True

        # ---- D5 transit filter (plan §5b, evidence states only) ----
        W = float(entry_dwell_s or 0.0)
        pending = False
        if rule == "evidence":
            self._hvac_dwell_s[room_name] = W
            d5 = self._d5_update(
                room_name=room_name, room_type=room_type,
                override_day=override_day, now=now, ev=last_evidence,
                active=(bool(evidence_active) if refresh_ok is not False else False),
                onset=onset, W=W, away_edge=bool(away_edge), prev_out=prev_out,
                zone_id=zone_id, return_window_s=return_window_s,
                skip_entry_wait=skip_entry_wait,
            )
            if d5["cold"] and W > 0:
                ev_out = ev_out and d5["persisted"]
                pending = d5["pending"]
        else:
            # Night: no D5 (plan §4.3); a live episode is dropped and the
            # per-pass D5 fields are reset (A-LOW-1).
            self._clear_episode(room_name)
            self._hvac_cold[room_name] = False
            self._hvac_exempt_reason[room_name] = None
        self._hvac_pending[room_name] = pending

        if rule == "evidence":
            out = ev_out
        else:  # night: never shorter than the shadow (INV-5)
            out = shadow_out or ev_out
        out = bool(out)

        # ---- arm / release bookkeeping (plan §4.2 step 5, §5b.3) ----
        if out and not prev_out:
            self._hvac_armed_at[room_name] = now
            self._hvac_ep_armed[room_name] = True
            onsets = self._hvac_episode_onsets.get(room_name) or []
            ep_start = self._hvac_episode_start.get(room_name)
            if rule == "evidence" and self._hvac_cold.get(room_name) and W > 0:
                # D0c arm-class split (diagnostic only).
                if len(onsets) > 1:
                    cls = "joined_transit"
                elif not evidence_active:
                    cls = "exit_pulse"
                else:
                    cls = "clean"
                arm_onset = ep_start if ep_start is not None else now
            else:
                cls = "immediate"
                arm_onset = onset if isinstance(onset, datetime) else now
            self._hvac_arm_class[room_name] = cls
            # The arm's evidence span is measured from this onset to the
            # last evidence before the release (plan §5b.3: "an arm whose
            # evidence spanned at least W").
            self._hvac_arm_onset[room_name] = arm_onset
        elif out:
            self._hvac_ep_armed[room_name] = True
        elif prev_out:
            arm_onset = self._hvac_arm_onset.get(room_name)
            if arm_onset is not None and last_evidence is not None:
                span = max(0.0, (last_evidence - arm_onset).total_seconds())
            else:
                span = 0.0
            self._hvac_arm_span_s[room_name] = span
            if rule == "evidence" and (W <= 0 or span >= W):
                # Room-only exemption anchor: renewed ONLY by an arm whose
                # evidence spanned >= W — a ghost blip cannot chain it.
                # Anchored on the room's EVIDENCE RELEASE (`ev + hold`),
                # not on the pass that observed it (A-LOW-3).
                _rel = self._hvac_day_release_at.get(room_name)
                self._hvac_ev_released_at[room_name] = _rel if _rel is not None else now
        self._hvac_rule[room_name] = rule
        self._hvac_output[room_name] = out
        return out

    # ------------------------------------------------------------------
    # D5 transit filter — episode machinery (plan §5b.1 / §5b.2)
    # ------------------------------------------------------------------
    def _clear_episode(self, room_name: str) -> None:
        self._hvac_episode_start.pop(room_name, None)
        self._hvac_episode_onsets.pop(room_name, None)
        self._hvac_episode_prev_ev.pop(room_name, None)
        self._hvac_episode_closed_s.pop(room_name, None)
        self._hvac_episode_active_s.pop(room_name, None)

    def _lapse_episode(self, room_name: str, zone_id: str | None) -> None:
        """An unarmed episode lapsed: count it (D5 C1-D) and drop it."""
        if not self._hvac_ep_armed.get(room_name, False) and zone_id:
            self.transit_filtered_today[zone_id] = (
                self.transit_filtered_today.get(zone_id, 0) + 1
            )
        self._clear_episode(room_name)

    def d5_join_window_s(self, room_name: str, W: float) -> float:
        """J = min(hold_ev, W) for the room (plan §5b.2)."""
        meta = self._room_meta_last_pass.get(room_name) or {}
        from ..const import ROOM_TYPE_GENERIC
        hold = self._evidence_hold_seconds(
            str(meta.get("room_type", ROOM_TYPE_GENERIC)),
            meta.get("hvac_hold_override_day"),
        )
        return float(min(hold, W)) if W > 0 else 0.0

    def _d5_update(
        self,
        *,
        room_name: str,
        room_type: str,
        override_day: int | None,
        now: datetime,
        ev: datetime | None,
        active: bool,
        onset: datetime | None,
        W: float,
        away_edge: bool,
        prev_out: bool,
        zone_id: str | None,
        return_window_s: float | None = None,
        skip_entry_wait: bool = False,
    ) -> dict[str, Any]:
        """Update the room's D5 episode from (ev, active, onset) at `now`
        and return {cold, live, persisted, pending, episode_start, J}.

        Idempotent for identical inputs (the listener and the producer may
        both call it for the same refresh). Rule (plan §5b.1):
          exempt = released_at within the Return Window (knob 52; 0 = off)
          skip_entry_wait (per-room option) -> never cold
          cold   = away_edge and not prev_out and not exempt
          not cold or W == 0 -> episode cleared, output unfiltered
          else: episode join/lapse (§5b.2); persisted = W == 0 or
                (active and now - start >= W) or (ev - start >= W)
        """
        if return_window_s is None:
            return_window_s = getattr(self, "_last_return_window_s", None)
        if return_window_s is None:
            from .hvac_const import DEFAULT_HVAC_RETURN_WINDOW_MINUTES as _DRW  # noqa: PLC0415
            return_window_s = float(_DRW) * 60.0
        hold_ev = self._evidence_hold_seconds(room_type, override_day)
        J = float(min(hold_ev, W)) if W > 0 else 0.0
        released_at = self._hvac_ev_released_at.get(room_name)
        # Return Window (knob 52, live): 0 = exemption off.
        exempt = (
            float(return_window_s) > 0
            and released_at is not None
            and 0 <= (now - released_at).total_seconds() <= float(return_window_s)
        )
        # Per-room "Skip entry wait" (ruling 3): the room is never cold.
        cold = bool(away_edge) and not prev_out and not exempt and not bool(skip_entry_wait)
        self._hvac_exempt_reason[room_name] = (
            "same_room_return" if (bool(away_edge) and not prev_out and exempt) else
            ("skip_entry_wait" if (bool(away_edge) and not prev_out and skip_entry_wait) else None)
        )
        self._hvac_cold[room_name] = cold
        if not cold or W <= 0:
            # Unfiltered: the plain evidence rule decides.
            self._clear_episode(room_name)
            return {
                "cold": cold, "live": False, "persisted": True, "pending": False,
                "episode_start": None, "J": J,
            }
        # Cold: NOTHING arms unless a live episode has persisted (INV-D5 a).
        result: dict[str, Any] = {
            "cold": True, "live": False, "persisted": False, "pending": False,
            "episode_start": None, "J": J,
        }
        if ev is None:
            self._clear_episode(room_name)
            return result

        onset_cur = onset if isinstance(onset, datetime) else ev
        if onset_cur > ev:
            onset_cur = ev
        start = self._hvac_episode_start.get(room_name)
        onsets = self._hvac_episode_onsets.get(room_name)
        prev_ev = self._hvac_episode_prev_ev.get(room_name)

        if start is None or onsets is None or prev_ev is None:
            # No live episode. Evidence older than J -> nothing to track.
            if not active and (now - ev).total_seconds() > J:
                self._clear_episode(room_name)
                return result
            start = onset_cur
            onsets = [onset_cur]
            self._hvac_episode_start[room_name] = start
            self._hvac_episode_onsets[room_name] = onsets
            self._hvac_episode_closed_s[room_name] = 0.0
            self._hvac_ep_armed[room_name] = False
            prev_ev = ev
        else:
            if onset_cur > onsets[-1]:
                # A new evidence stretch began since the last update.
                if (onset_cur - prev_ev).total_seconds() > J:
                    # Gap beyond J: the old episode lapsed; start anew.
                    self._lapse_episode(room_name, zone_id)
                    start = onset_cur
                    onsets = [onset_cur]
                    self._hvac_episode_start[room_name] = start
                    self._hvac_episode_onsets[room_name] = onsets
                    self._hvac_episode_closed_s[room_name] = 0.0
                    self._hvac_ep_armed[room_name] = False
                else:
                    # Join: close the previous stretch, append the onset.
                    closed = self._hvac_episode_closed_s.get(room_name, 0.0)
                    closed += max(0.0, (prev_ev - onsets[-1]).total_seconds())
                    self._hvac_episode_closed_s[room_name] = closed
                    onsets.append(onset_cur)
            prev_ev = max(prev_ev, ev)
        self._hvac_episode_prev_ev[room_name] = prev_ev

        # Lapse: no arm and the evidence is older than J.
        if not active and (now - prev_ev).total_seconds() > J:
            self._lapse_episode(room_name, zone_id)
            return result

        closed = self._hvac_episode_closed_s.get(room_name, 0.0)
        self._hvac_episode_active_s[room_name] = closed + max(
            0.0, (prev_ev - onsets[-1]).total_seconds(),
        )
        persisted = (
            (active and (now - start).total_seconds() >= W)
            or (prev_ev - start).total_seconds() >= W
        )
        result.update({
            "live": True, "persisted": bool(persisted),
            "pending": not persisted, "episode_start": start,
        })
        return result

    @staticmethod
    def _read_room_evidence(coordinator: Any) -> tuple[datetime | None, bool, datetime | None, bool]:
        """(last_evidence, evidence_active, onset, refresh_ok) read
        defensively from a room coordinator: `isinstance(..., datetime)`
        (a MagicMock or a legacy fake yields None), `is True` for the active
        flag, `last_update_success is not False` for refresh health."""
        ev_raw = act_raw = onset_raw = None
        try:
            g = getattr(coordinator, "get_last_hvac_evidence_time", None)
            ev_raw = g() if callable(g) else None
            a = getattr(coordinator, "is_hvac_evidence_active", None)
            act_raw = a() if callable(a) else None
            o = getattr(coordinator, "get_hvac_evidence_onset", None)
            onset_raw = o() if callable(o) else None
        except Exception:  # noqa: BLE001 — never let a room read fault the pass
            ev_raw = act_raw = onset_raw = None
        return (
            ev_raw if isinstance(ev_raw, datetime) else None,
            act_raw is True,
            onset_raw if isinstance(onset_raw, datetime) else None,
            getattr(coordinator, "last_update_success", True) is not False,
        )

    def d5_room_probe(
        self, room_name: str, now: datetime, entry_dwell_s: float, away_edge: bool,
    ) -> dict[str, Any] | None:
        """Listener-side D5 probe (plan §5.4 step 4): update the room's
        episode from the LIVE accessors and return the `_d5_update` result,
        or None when D5 does not apply (no coordinator / not an evidence
        state / hallway)."""
        from ..const import ROOM_TYPE_GENERIC, ROOM_TYPE_HALLWAY
        meta = self._room_meta_last_pass.get(room_name) or {}
        coordinator = self._room_coord_last_pass.get(room_name)
        if coordinator is None:
            return None
        if self._hvac_rule_for_state(self._last_house_state) != "evidence":
            return None
        room_type = str(meta.get("room_type", ROOM_TYPE_GENERIC))
        if room_type == ROOM_TYPE_HALLWAY:
            return None
        ev, active, onset, refresh_ok = self._read_room_evidence(coordinator)
        zone_id = None
        for z in self._zones.values():
            if room_name in (getattr(z, "rooms", []) or []):
                zone_id = z.zone_id
                break
        return self._d5_update(
            room_name=room_name, room_type=room_type,
            override_day=meta.get("hvac_hold_override_day"), now=now, ev=ev,
            active=(active if refresh_ok else False), onset=onset,
            W=float(entry_dwell_s or 0.0), away_edge=bool(away_edge),
            prev_out=bool(self._hvac_output.get(room_name, False)),
            zone_id=zone_id,
            # fix-up 1 (ruling 3): the listener probe honours the per-room
            # "Skip entry wait" too, else a skip room would wait for the
            # arm re-check / tick instead of queuing a fast run at once.
            skip_entry_wait=bool(meta.get("hvac_skip_entry_wait", False)),
        )

    def room_is_pending(self, room_name: str) -> bool:
        return bool(self._hvac_pending.get(room_name, False))

    def room_last_evidence_live(self, room_name: str) -> datetime | None:
        coordinator = self._room_coord_last_pass.get(room_name)
        if coordinator is None:
            return None
        return self._read_room_evidence(coordinator)[0]

    # ------------------------------------------------------------------
    # v5.103.20 — exact release instant helpers (plan §4.5), sync + pure
    # ------------------------------------------------------------------
    def _room_release_from(
        self,
        *,
        room_name: str,
        room_type: str,
        house_state: str | None,
        override_day: int | None,
        last_evidence: datetime | None,
        evidence_active: bool,
        refresh_ok: bool = True,
    ) -> tuple[str, datetime | None]:
        """Release verdict for one room: ("unbounded", None) while the room
        is held with no known end (active evidence, or the shadow riding
        `occupied`, or a legacy state); ("at", dt) when the release instant
        is known; ("none", None) when the room contributes nothing (hallway,
        never any evidence / arm)."""
        from datetime import timedelta as _td
        from ..const import ROOM_TYPE_HALLWAY
        from .hvac_const import HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S

        if room_type == ROOM_TYPE_HALLWAY:
            return ("none", None)
        rule = self._hvac_rule_for_state(house_state)
        if rule == "legacy":
            return ("unbounded", None)
        if rule == "evidence" and (
            self._hvac_pending.get(room_name, False)
            or not self._hvac_ep_armed.get(room_name, True)
        ):
            # D5 (plan §4.5): pending and never-armed episodes are excluded
            # from E(Z) — they never touch the grace clock.
            return ("none", None)
        if refresh_ok is not False and evidence_active:
            return ("unbounded", None)
        ev_rel: datetime | None = None
        if last_evidence is not None:
            ev_rel = last_evidence + _td(
                seconds=self._evidence_hold_seconds(room_type, override_day),
            )
            if (
                rule == "evidence"
                and refresh_ok is False
                and self._hvac_output.get(room_name, False)
                and HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S > 0
            ):
                ev_rel = max(
                    ev_rel,
                    last_evidence + _td(seconds=HVAC_EVIDENCE_REFRESH_FAIL_HOLD_S),
                )
        if rule == "evidence":
            return ("at", ev_rel) if ev_rel is not None else ("none", None)
        # night: the later of the shadow's tail end and the evidence release
        sh_rel: datetime | None
        if self._hvac_armed.get(room_name, False):
            tail = self._hvac_tail_until.get(room_name)
            if tail is None:
                return ("unbounded", None)  # shadow riding `occupied`
            sh_rel = tail
        else:
            sh_rel = self._hvac_shadow_release_at.get(room_name)
        cands = [x for x in (ev_rel, sh_rel) if x is not None]
        return ("at", max(cands)) if cands else ("none", None)

    def room_release_at(self, room_name: str) -> datetime | None:
        """LIVE release instant for a room (reads the coordinator accessors
        NOW, not the last pass — plan §4.5 / REV 2 #10). None while
        unbounded or unknown."""
        kind, at = self._room_release_info_live(room_name)
        return at if kind == "at" else None

    def _room_release_info_live(self, room_name: str) -> tuple[str, datetime | None]:
        meta = self._room_meta_last_pass.get(room_name) or {}
        coordinator = self._room_coord_last_pass.get(room_name)
        if coordinator is None:
            return ("none", None)
        from ..const import ROOM_TYPE_GENERIC
        room_type = str(meta.get("room_type", ROOM_TYPE_GENERIC))
        ev = None
        active = False
        try:
            _g = getattr(coordinator, "get_last_hvac_evidence_time", None)
            _raw = _g() if callable(_g) else None
            ev = _raw if isinstance(_raw, datetime) else None
            _a = getattr(coordinator, "is_hvac_evidence_active", None)
            active = (_a() if callable(_a) else None) is True
        except Exception:  # noqa: BLE001
            ev, active = None, False
        refresh_ok = getattr(coordinator, "last_update_success", True) is not False
        return self._room_release_from(
            room_name=room_name,
            room_type=room_type,
            house_state=self._last_house_state,
            override_day=meta.get("hvac_hold_override_day"),
            last_evidence=ev,
            evidence_active=active,
            refresh_ok=refresh_ok,
        )

    def zone_release_at(self, zone_id: str) -> datetime | None:
        """Max LIVE room release over the zone's rooms; None if any room is
        unbounded or no room has a known release."""
        zone = self._zones.get(zone_id)
        if zone is None:
            return None
        best: datetime | None = None
        for room_name in getattr(zone, "rooms", []) or []:
            kind, at = self._room_release_info_live(room_name)
            if kind == "unbounded":
                return None
            if kind == "at" and at is not None and (best is None or at > best):
                best = at
        return best

    def zone_away_due_at(self, zone_id: str, grace_s: float) -> datetime | None:
        """`zone_release_at + grace_s`, or None."""
        from datetime import timedelta as _td
        rel = self.zone_release_at(zone_id)
        if rel is None:
            return None
        return rel + _td(seconds=float(grace_s))

    def _away_due_at_attr(self, zone, away_grace_s: float | None) -> str | None:
        """DISPLAY-ONLY `away_due_at` (ISO local) for the zone status sensor:
        `zone_away_due_at` (= live release + grace) while the zone is
        HVAC-empty and the due time is still ahead; None while it is
        HVAC-occupied, once the due time has passed (the exit is done or
        overdue — never show a past instant), when the grace is unknown, or
        when the release is unknown / unbounded. Never raises."""
        try:
            if away_grace_s is None or zone.any_room_hvac_occupied:
                return None
            due = self.zone_away_due_at(zone.zone_id, float(away_grace_s))
            if due is None or dt_util.utcnow() >= due:
                return None
            return dt_util.as_local(due).isoformat()
        except Exception:  # noqa: BLE001
            return None

    def _zone_release_bound(self, zone, now: datetime, house_state: str | None) -> datetime | None:
        """Back-fill helper (plan §4.5): max release over the zone's rooms
        from THIS pass's stored evidence, counting only releases <= now.
        Used only when the zone is fused-empty on the pass."""
        best: datetime | None = None
        for room_name in getattr(zone, "rooms", []) or []:
            meta = self._room_meta_last_pass.get(room_name) or {}
            coordinator = self._room_coord_last_pass.get(room_name)
            if coordinator is None:
                continue
            from ..const import ROOM_TYPE_GENERIC
            room_type = str(meta.get("room_type", ROOM_TYPE_GENERIC))
            kind, at = self._room_release_from(
                room_name=room_name,
                room_type=room_type,
                house_state=house_state,
                override_day=meta.get("hvac_hold_override_day"),
                last_evidence=self._hvac_last_ev.get(room_name),
                evidence_active=bool(self._hvac_last_active.get(room_name, False)),
                refresh_ok=getattr(coordinator, "last_update_success", True) is not False,
            )
            if kind == "at" and at is not None and at <= now and (
                best is None or at > best
            ):
                best = at
        return best

    def _shadow_hvac_occupied(
        self,
        *,
        room_name: str,
        room_type: str,
        state_occupied: bool,
        now: datetime,
        house_state: str | None,
        override_day: int | None = None,
        override_night: int | None = None,
    ) -> bool:
        """SHADOW — the v5.103.19 D1 state machine, byte-for-byte.

        Ride grace-held STATE_OCCUPIED + per-room tail. Kind is NOT
        consulted (CRIT-1 closure). Hallway is filtered upstream. Sole
        writer of `_hvac_armed` / `_hvac_prev_state_occupied` /
        `_hvac_tail_until` / `_hvac_arm_source` (INV-5).
        """
        from datetime import timedelta as _td

        # D-HIGH-1 fix-up: mark the room as seen so its zone can be
        # considered HVAC-established. Populated on every producer call,
        # even when state_occupied is False — presence of a live
        # producer read is what "established" means.
        self._hvac_seen.add(room_name)
        prev = self._hvac_prev_state_occupied.get(room_name, False)
        armed = self._hvac_armed.get(room_name, False)

        # Rising edge: arm.
        if state_occupied and not prev:
            self._hvac_armed[room_name] = True
            self._hvac_tail_until.pop(room_name, None)
            self._hvac_arm_source[room_name] = "edge"
            self._hvac_prev_state_occupied[room_name] = True
            return True

        # Update prev after edge-detection so downstream logic sees the
        # correct current value.
        self._hvac_prev_state_occupied[room_name] = state_occupied

        if not armed:
            # Never armed (or already released) — nothing to hold.
            return False

        if state_occupied:
            # Held STATE_OCCUPIED — clear any pending tail (edge is fresh
            # again) and ride purely on the grace-held bool.
            self._hvac_tail_until.pop(room_name, None)
            self._hvac_arm_source[room_name] = "held"
            return True

        # Falling / vacant — schedule or evaluate the tail.
        tail_expiry = self._hvac_tail_until.get(room_name)
        if tail_expiry is None:
            hold_s = self._effective_hvac_hold_seconds(
                room_type, house_state,
                override_day=override_day,
                override_night=override_night,
                room_name=room_name,
            )
            if hold_s <= 0:
                # No tail configured — release immediately.
                self._hvac_armed[room_name] = False
                self._hvac_arm_source[room_name] = "released_no_tail"
                return False
            self._hvac_tail_until[room_name] = now + _td(seconds=hold_s)
            self._hvac_arm_source[room_name] = "tail"
            return True

        if now < tail_expiry:
            self._hvac_arm_source[room_name] = "tail"
            return True

        # Tail expired.
        self._hvac_armed[room_name] = False
        self._hvac_tail_until.pop(room_name, None)
        self._hvac_arm_source[room_name] = "released_tail_expired"
        return False

    # ------------------------------------------------------------------
    # HVAC-DEGRADED-ROOM-TRIPWIRE-1 (2026-09-26) — live-room classification
    # ------------------------------------------------------------------
    def _classify_all_rooms(self, now: datetime, only_rooms: set[str] | None = None) -> None:
        """Classify every known ROOM entry into live | transient | excluded.

        v5.103.20 fix-up 1 (B-M3): `only_rooms` (a zone-filtered fast run)
        re-classifies ONLY those rooms; every other room keeps its previous
        classification and non-loaded clock, and emits nothing.

        Called from `update_room_conditions` once per pass. Result stored
        in `self._room_hvac_class[room_name] = (kind, reason)`. Also
        maintains `_room_non_loaded_since` (seed on first non-LOADED,
        clear on LOADED) and enqueues `_pending_degraded_events` for
        rooms crossing into EXCLUDED (immediate or past-grace) that have
        not been notified this boot.

        Classification per REV-2 F5 (supersedes AM-2):
        - EXCLUDED immediately: `disabled_by is not None`, `SETUP_ERROR`,
          `MIGRATION_ERROR`, `SETUP_RETRY`.
        - TRANSIENT (BLOCKS; after GRACE_S continuous → EXCLUDED +
          WARN+NM): `NOT_LOADED`, `SETUP_IN_PROGRESS`,
          `UNLOAD_IN_PROGRESS`, `FAILED_UNLOAD`, unknown future member.
        - LIVE: `LOADED`.

        Fail-CLOSED for retreat: an entry we cannot classify (enum
        import fails, or entry state read raises) is TRANSIENT — see
        `_integration_entry_is_loaded` at aggregation.py:385-394 for
        the analogous fail-open-for-loaded / fail-closed-for-retreat
        directionality.
        """
        _prev_class = dict(getattr(self, "_room_hvac_class", {}) or {})
        self._room_hvac_class = {}
        if only_rooms is not None:
            for _r, _v in _prev_class.items():
                if _r not in only_rooms:
                    self._room_hvac_class[_r] = _v
        try:
            from homeassistant.config_entries import ConfigEntryState as _CES
        except Exception:  # noqa: BLE001
            _CES = None

        _IMMEDIATE_EXCLUDE = {
            "SETUP_ERROR": "setup_error",
            "MIGRATION_ERROR": "migration_error",
            "SETUP_RETRY": "setup_retry",
        }
        _TRANSIENT = {
            "NOT_LOADED", "SETUP_IN_PROGRESS", "UNLOAD_IN_PROGRESS",
            "FAILED_UNLOAD",
        }
        # FIX-UP round 3 item 7 (2026-09-26): prune sticky-failed rooms
        # whose config entry no longer exists so a removed-and-re-added
        # room isn't permanently sticky. Once a name is no longer in
        # `_room_entry_by_name` it will be handled below as "entry_removed"
        # (excluded) — and if a fresh entry ever appears with the same
        # name and LOADED, the sticky bit must not carry over.
        _stale_sticky = self._sticky_failed_rooms - set(self._room_entry_by_name)
        if _stale_sticky:
            self._sticky_failed_rooms -= _stale_sticky
        # FIX-UP item 3: rooms that appear in some zone.rooms but no
        # config entry exists for them any more (mid-session removal) are
        # EXCLUDED immediately with reason "entry_removed" and get one
        # WARN+NM (debounced).
        for zroom in self._rooms_in_any_zone:
            if zroom in self._room_entry_by_name:
                continue
            if only_rooms is not None and zroom not in only_rooms:
                continue
            self._room_hvac_class[zroom] = ("excluded", "entry_removed")
            self._room_non_loaded_since.pop(zroom, None)
            self._maybe_emit_degraded(zroom, "entry_removed")
        for room_name, entry in self._room_entry_by_name.items():
            if only_rooms is not None and room_name not in only_rooms:
                continue
            # disabled_by wins over state.
            try:
                disabled_by = getattr(entry, "disabled_by", None)
            except Exception:  # noqa: BLE001
                disabled_by = None
            if disabled_by is not None:
                reason = "disabled_by_user" if str(
                    getattr(disabled_by, "value", disabled_by)
                ) == "user" else "disabled_by_integration"
                self._room_hvac_class[room_name] = ("excluded", reason)
                self._room_non_loaded_since.pop(room_name, None)
                self._maybe_emit_degraded(room_name, reason)
                continue

            if _CES is None:
                # ConfigEntryState enum unavailable → fail-CLOSED for
                # retreat = TRANSIENT (BLOCKS). This is the correct
                # direction: unable to prove LOADED → do not authorize
                # a retreat. Distinct from aggregation.py:385-394 which
                # returns True on the same failure because THERE "loaded"
                # means "counted live" (allow); HERE "not-loaded" would
                # be "counted excluded" (leaves denominator, allow).
                self._room_hvac_class[room_name] = ("transient", "state_enum_unavailable")
                self._room_non_loaded_since.setdefault(room_name, now)
                continue

            try:
                state = getattr(entry, "state", None)
                state_name = getattr(state, "name", None) or str(state)
            except Exception:  # noqa: BLE001
                state = None
                state_name = "unknown"

            if state is _CES.LOADED or state_name == "LOADED":
                self._room_hvac_class[room_name] = ("live", "loaded")
                self._room_non_loaded_since.pop(room_name, None)
                # FIX-UP item 1: an observed LOADED transition is the
                # ONLY way a sticky-failed room returns to live.
                self._sticky_failed_rooms.discard(room_name)
                continue

            if state_name in _IMMEDIATE_EXCLUDE:
                reason = _IMMEDIATE_EXCLUDE[state_name]
                self._room_hvac_class[room_name] = ("excluded", reason)
                self._room_non_loaded_since.pop(room_name, None)
                # FIX-UP item 1: mark sticky so a subsequent
                # SETUP_IN_PROGRESS phase of the HA retry cycle does NOT
                # flip us back to TRANSIENT (which would make the zone
                # transient-blocked and flap).
                self._sticky_failed_rooms.add(room_name)
                self._maybe_emit_degraded(room_name, reason)
                continue

            if state_name in _TRANSIENT:
                # FIX-UP item 1: sticky-failed rooms stay EXCLUDED
                # through the HA retry cycle's SETUP_IN_PROGRESS phase;
                # only a real LOADED observation clears stickiness.
                if room_name in self._sticky_failed_rooms:
                    self._room_hvac_class[room_name] = (
                        "excluded", "sticky_failed",
                    )
                    self._room_non_loaded_since.pop(room_name, None)
                    continue
                first = self._room_non_loaded_since.setdefault(room_name, now)
                elapsed = (now - first).total_seconds()
                if elapsed >= HVAC_LIVE_ROOM_TRANSIENT_GRACE_S:
                    self._room_hvac_class[room_name] = (
                        "excluded", "transient_past_grace",
                    )
                    self._maybe_emit_degraded(
                        room_name, "transient_past_grace",
                    )
                else:
                    self._room_hvac_class[room_name] = (
                        "transient", state_name.lower(),
                    )
                continue

            # Unknown / future HA member — fail-CLOSED (blocks) + WARN
            # once per state name, then age it out to EXCLUDED via the
            # grace timer just like a known transient.
            if state_name not in self._unknown_state_warned:
                self._unknown_state_warned.add(state_name)
                _LOGGER.warning(
                    "HVAC live-room: unknown ConfigEntryState %r for room %s "
                    "— treating as TRANSIENT (fail-closed)",
                    state_name, room_name,
                )
            first = self._room_non_loaded_since.setdefault(room_name, now)
            if (now - first).total_seconds() >= HVAC_LIVE_ROOM_TRANSIENT_GRACE_S:
                self._room_hvac_class[room_name] = (
                    "excluded", f"unknown_state_past_grace:{state_name}",
                )
                self._maybe_emit_degraded(
                    room_name, f"unknown_state_past_grace:{state_name}",
                )
            else:
                self._room_hvac_class[room_name] = (
                    "transient", f"unknown:{state_name}",
                )

        self._hvac_classification_ready = True

    def _maybe_emit_degraded(self, room_name: str, reason: str) -> None:
        """Enqueue a transient→excluded / immediate-exclusion event.

        Debounced per-(boot, room_name): each room fires WARN+NM at most
        once. The HVACCoordinator drains `_pending_degraded_events`
        after the sync producer returns (async NM emission, per REV-2
        D3 / F9 — the sync gate must NEVER create_task).

        FIX-UP item 5: only emit for rooms that belong to at least one
        HVAC zone — unzoned / hallway-only rooms are classified but must
        not surface a "hvac degraded room" alert.
        """
        if room_name not in self._rooms_in_any_zone:
            return
        if room_name in self._excluded_ever_notified:
            return
        self._excluded_ever_notified.add(room_name)
        self._pending_degraded_events.append((room_name, reason))
        _LOGGER.warning(
            "HVAC live-room: room %s classified EXCLUDED (reason=%s) — "
            "leaves zone denominator; a zone consisting only of excluded "
            "rooms will never retreat",
            room_name, reason,
        )

    def drain_degraded_events(self) -> list[tuple[str, str]]:
        """Return + clear pending (room_name, reason) events.

        Consumed by HVACCoordinator to fire the NM notification off the
        sync producer path (REV-2 D3 / F9).
        """
        events = list(self._pending_degraded_events)
        self._pending_degraded_events.clear()
        return events

    def _classify_zone_rooms(
        self, zone: ZoneState,
    ) -> tuple[list[str], list[str], list[str]]:
        """Return (excluded, transient, live) for `zone.rooms`.

        A room absent from `_room_hvac_class` (mid-session removal /
        never scanned) is TRANSIENT — fail-closed for retreat.
        """
        excluded: list[str] = []
        transient: list[str] = []
        live: list[str] = []
        for r in zone.rooms:
            cls = self._room_hvac_class.get(r)
            if cls is None:
                transient.append(r)
                continue
            kind, _ = cls
            if kind == "excluded":
                excluded.append(r)
            elif kind == "transient":
                transient.append(r)
            else:
                live.append(r)
        return excluded, transient, live

    def _live_zone_rooms(self, zone: ZoneState) -> list[str]:
        """Return the LIVE subset of `zone.rooms` (see _classify_zone_rooms)."""
        _e, _t, live = self._classify_zone_rooms(zone)
        return live

    # FIX-UP item 7 (2026-09-26): guarded diag helpers so a poisoned
    # naive datetime in `_room_non_loaded_since` or a classifier fault
    # never breaks the zone status sensor. Each helper returns [] on
    # exception; the zone status sensor keeps rendering.
    def _safe_diag_live_rooms(self, zone: ZoneState) -> list[str]:
        try:
            if self._hvac_classification_ready:
                return self._live_zone_rooms(zone)
            return list(zone.rooms)
        except Exception:  # noqa: BLE001
            return []

    def _safe_diag_excluded_rooms(self, zone: ZoneState) -> list[dict]:
        try:
            if not self._hvac_classification_ready:
                return []
            return [
                {
                    "name": r,
                    "reason": self._room_hvac_class.get(r, ("", ""))[1],
                }
                for r in self._classify_zone_rooms(zone)[0]
            ]
        except Exception:  # noqa: BLE001
            return []

    def _safe_diag_transient_rooms(self, zone: ZoneState) -> list[dict]:
        try:
            if not self._hvac_classification_ready:
                return []
            out: list[dict] = []
            _now = dt_util.utcnow()
            for r in self._classify_zone_rooms(zone)[1]:
                seconds_non_loaded: float | None
                try:
                    first = self._room_non_loaded_since.get(r)
                    if first is None:
                        seconds_non_loaded = None
                    else:
                        seconds_non_loaded = round(
                            (_now - first).total_seconds(), 1,
                        )
                except Exception:  # noqa: BLE001
                    # Poisoned entry (e.g. naive datetime) — surface
                    # None rather than break the whole attribute.
                    seconds_non_loaded = None
                out.append({
                    "name": r,
                    "state": self._room_hvac_class.get(r, ("", ""))[1],
                    "seconds_non_loaded": seconds_non_loaded,
                })
            return out
        except Exception:  # noqa: BLE001
            return []

    def _safe_diag_coord_absent_rooms(self, zone: ZoneState) -> list[str]:
        """FIX-UP item 7 (Rev D F5): rooms whose coordinator was absent on
        the latest producer pass. Distinguishes LOADED-but-coordinator-
        absent (a real F4 hazard) from entry-state degradation."""
        try:
            absent = self._coordinator_absent_this_pass
            return [r for r in zone.rooms if r in absent]
        except Exception:  # noqa: BLE001
            return []

    def is_zone_transient_blocked(self, zone_id: str) -> bool:
        """FIX-UP item 2: True iff the zone has at least one TRANSIENT
        room (loading / reloading / unloading within the grace window).

        Callers (row-1 preset flip, D9 compose-away) use this to HOLD
        the current preset when the ONLY reason establishment is False
        is a transient sibling — matching the operator rule "match
        occupancy IN THE ZONE" during the reload window instead of
        retreating to the house-state baseline on a sibling room's
        reload.

        Fail-CLOSED (returns False) on any lookup exception so the
        no-hold path is the default.
        """
        try:
            if not self._hvac_classification_ready:
                return False
            zone = self._zones.get(zone_id)
            if zone is None:
                return False
            _e, transient, _l = self._classify_zone_rooms(zone)
            return bool(transient)
        except Exception:  # noqa: BLE001
            return False

    def is_zone_hvac_established(self, zone_id: str) -> bool:
        """Live-room establishment check (HVAC-DEGRADED-ROOM-TRIPWIRE-1,
        REV-2 D2, 2026-09-26).

        A zone is HVAC-ESTABLISHED iff, after classifying every
        `zone.rooms` entry into LIVE / TRANSIENT / EXCLUDED
        (`_classify_all_rooms`):
        - `transient` is empty (any loading/reloading sibling BLOCKS —
          F-INV-A: a room reload's stale `_hvac_seen` entry must not
          satisfy the gate); AND
        - `live` is non-empty (F-INV-C: an all-dead zone stays
          UNESTABLISHED); AND
        - every LIVE room is coordinator-present on the latest producer
          pass (`_coordinator_absent_this_pass`) AND has been observed
          by the D1 producer at least once (`_hvac_seen`).

        EXCLUDED rooms (disabled / setup_error / migration_error /
        sticky-failed / entry-removed / transient past grace) LEAVE
        the denominator — a zone with a permanently-disabled room can
        still establish and retreat on its remaining LIVE rooms. This
        supersedes the round-5 `all(zone.rooms in _hvac_seen)` rule
        that left the feature INERT for any zone with a single
        permanently-degraded room.

        Reload-window rationale: the invariant is defended layered —
        transient rooms BLOCK for `HVAC_LIVE_ROOM_TRANSIENT_GRACE_S`
        (300s) after first non-LOADED observation; the coordinator
        awaits `async_config_entry_first_refresh` before publishing
        (`__init__.py:4959-4962`); an entry that cannot be classified
        is TRANSIENT (fail-CLOSED for retreat).

        Fallback: if `update_room_conditions` has not run yet
        (`_hvac_classification_ready is False` — unit tests seeding
        `_hvac_seen` directly), fall back to the round-5
        `all(r in _hvac_seen)` semantics so existing test contracts
        hold until the first producer pass.

        Callers (row-1, D7, D9, F4 row-10) use this via
        `conditioning_retreat_ok` — the single retreat authorization
        helper. Row-1 additionally consults
        `is_zone_transient_blocked` to hold the current preset (no
        write) during the reload window instead of falling back to
        the house-state target.
        """
        zone = self._zones.get(zone_id)
        if zone is None:
            return False
        rooms = list(zone.rooms or [])
        if not rooms:
            return False
        # HVAC-DEGRADED-ROOM-TRIPWIRE-1 REV-2 D2 (2026-09-26):
        # Fallback for callers that haven't driven `update_room_conditions`
        # yet (unit tests seeding `_hvac_seen` directly). Preserves round-5
        # `all(_hvac_seen)` semantics so existing test contracts hold.
        if not self._hvac_classification_ready:
            return all(r in self._hvac_seen for r in rooms)
        excluded, transient, live = self._classify_zone_rooms(zone)
        # REV-2 D2 step 2 (AM-1 fix): any TRANSIENT room BLOCKS outright.
        # A room reloading (LOADED→SETUP_IN_PROGRESS→LOADED) may still be
        # in `_hvac_seen` from a prior pass; the synthetic-empty branch
        # in the D1 producer (hvac_zones.py:616-641) would let its zone
        # read fused-empty and retreat during the reload window. Blocking
        # on ANY transient closes the cold-retreat hazard the round-5
        # revert existed to defend.
        if transient:
            return False
        # REV-2 D2 step 3 / F-INV-C: an all-dead zone stays UNESTABLISHED.
        if not live:
            return False
        # REV-2 D2 step 4 (F4 conjunct): every live room must be LOADED
        # AND have a present room coordinator on the latest producer pass
        # AND have been observed by the D1 producer at least once.
        return all(
            r in self._hvac_seen and r not in self._coordinator_absent_this_pass
            for r in live
        )

    def conditioning_retreat_ok(self, zone) -> bool:
        """F3 fix-up round 4 (2026-09-17): unified retreat-authorization.

        Single helper called from row-1 (preset-flip retreat gate), D7
        (night-trust suppression), D9 (DPM compose-away), and F4 row-10
        (arrester comfort_delay_active). Returns True IFF the zone is
        HVAC-ESTABLISHED AND fused-empty — the two conditions that
        together authorize a conditioning retreat.

        Reset-only backstop (operator-decided round 4): when the zone
        is UNESTABLISHED, retreat is NEVER authorized — occupancy-alone
        decides once established. Person-trust preserve was dropped
        from the ESTABLISHED path (it was over-preserving empty zones
        while a phone read `home` elsewhere in the house — the
        "any-resident-home was holding every empty zone all night"
        failure). Sensor degradation while ESTABLISHED is the mmWave
        hold's job, not the backstop's; see parked
        HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1.

        Fail-CLOSED behavior when the zone is missing / unavailable —
        callers observe `False` (do NOT retreat) so an accessor fault
        never flips into a spurious retreat.
        """
        try:
            zone_id = getattr(zone, "zone_id", None)
            if zone_id is None:
                return False
            if not self.is_zone_hvac_established(zone_id):
                return False
            _fused = getattr(zone, "any_room_hvac_occupied", None)
            if _fused is None:
                # Legacy fake shape — fall through to lighting-fused so
                # bare test zones don't spuriously retreat.
                _fused = getattr(zone, "any_room_occupied", True)
            return not bool(_fused)
        except Exception:  # noqa: BLE001 — defensive; never raise
            return False

    def zone_has_home_person(self, zone, hass) -> bool:
        """Person-trust backstop (D-HIGH-1 companion, 2026-09-17).

        Return True iff any of the zone's `zone_persons` phone trackers
        currently reads `home`. Used by the D7 / row-1 fail-open path
        as the v4.7.13-style veto when the fused signal is
        UNESTABLISHED or DEGRADED — preserve the preset (don't retreat)
        on the backstop of "a person known to be home".

        Fail-closed on missing / error — never let a lookup fault flip
        this into a spurious preserve.
        """
        try:
            persons = list(getattr(zone, "zone_persons", []) or [])
        except Exception:  # noqa: BLE001
            return False
        for person_entity in persons:
            try:
                st = hass.states.get(person_entity)
            except Exception:  # noqa: BLE001
                continue
            if st is not None and getattr(st, "state", None) == "home":
                return True
        return False

    def hvac_occupied_diag(self, room_name: str) -> dict[str, Any]:
        """Return a diagnostic snapshot for a room's D1 state (used by D2)."""
        _day_rel = self._hvac_day_release_at.get(room_name)
        _live_rel = None
        try:
            _live_rel = self.room_release_at(room_name)
        except Exception:  # noqa: BLE001
            _live_rel = None

        def _iso(v):
            return v.isoformat() if isinstance(v, datetime) else None
        return {
            "armed": bool(self._hvac_armed.get(room_name, False)),
            "tail_expires_at": (
                self._hvac_tail_until.get(room_name).isoformat()
                if self._hvac_tail_until.get(room_name) is not None
                else None
            ),
            "source": self._hvac_arm_source.get(room_name, "idle"),
            # v5.103.20: evidence-rule diagnostics (plan §3.2 display row).
            "rule": self._hvac_rule.get(room_name, "legacy"),
            "output": bool(self._hvac_output.get(room_name, False)),
            "evidence_release_at": _iso(_day_rel),
            "release_at": _iso(_live_rel),
            # D5 (plan §3.2): episode + arm diagnostics.
            "episode_start": _iso(self._hvac_episode_start.get(room_name)),
            "episode_onsets": [
                _iso(o) for o in (self._hvac_episode_onsets.get(room_name) or [])
            ],
            "episode_active_s": self._hvac_episode_active_s.get(room_name),
            "armed_at": _iso(self._hvac_armed_at.get(room_name)),
            "arm_span_s": self._hvac_arm_span_s.get(room_name),
            "arm_class": self._hvac_arm_class.get(room_name),
            "dwell_s": self._hvac_dwell_s.get(room_name),
            "exempt_reason": self._hvac_exempt_reason.get(room_name),
            "pending": bool(self._hvac_pending.get(room_name, False)),
            "cold": bool(self._hvac_cold.get(room_name, False)),
            "released_at": _iso(self._hvac_ev_released_at.get(room_name)),
        }

    def reset_daily_counters(self) -> None:
        """Reset daily counters for all zones (call at midnight)."""
        for zone in self._zones.values():
            zone.override_count_today = 0
            zone.ac_reset_count_today = 0
            zone.camera_face_arrivals_today = 0
            # D5 (v5.103.20) exposure metrics.
            zone.pending_hold_s_today = 0.0
        self.transit_filtered_today = {}


# ============================================================================
# Module-level helpers — usable from platform setup BEFORE coordinator init
# ============================================================================
#
# Bug Class #36 prevention. v4.5.12 shipped a regression where per-zone
# sensors were created from Zone Manager config WITHOUT applying the
# thermostat-keyed dedup that ZoneManager.async_discover_zones does. Two
# home zones sharing one AC produced two parallel sets of D7 sensors
# pointing at the same physical zone — see v4.5.13.1 review notes.
#
# All per-zone platform setup paths MUST call iter_canonical_hvac_zones
# rather than rolling their own iteration. Cross-platform consistency is
# enforced by quality/tests/test_v4513_1_zone_dedup.py.


def _zone_id_from_thermostat_pure(
    climate_entity: str,
    fallback_num: int,
    assigned_ids: set[str],
) -> str:
    """Pure variant of ZoneManager._zone_id_from_thermostat.

    Same logic; takes the set of already-assigned zone_ids explicitly
    instead of reading self._zones. Lets us derive consistent zone_ids
    during platform setup before the coordinator (and thus ZoneManager)
    exists.

    Returns zone_id matching `zone_N` pattern from the thermostat
    entity_id when possible (e.g., `climate.up_hallway_zone_2` → `zone_2`),
    falling back to `zone_<fallback_num>` and auto-incrementing past any
    collision.
    """
    match = re.search(r"(?:^|[_.\s])zone[_\s]?(\d+)", climate_entity)
    if match:
        candidate = f"zone_{match.group(1)}"
        if candidate not in assigned_ids:
            return candidate
    n = fallback_num
    while f"zone_{n}" in assigned_ids:
        n += 1
    return f"zone_{n}"


# =============================================================================
# v4.7.5 D3 — Caller inventory for iter_canonical_hvac_zones
# =============================================================================
# Per PLANNING_v4.7.5 §D3 and QUALITY_CONTEXT.md "Lazy Canonical Resolution":
# `iter_canonical_hvac_zones` is permitted ONLY on runtime / coordinator /
# platform-setup code paths. UI surfaces (config_flow.py) MUST NOT call this —
# they read raw house zones from `entry.options["zones"]` and let the runtime
# resolve canonical lazily.
#
# Approved callers as of v4.7.5 (run `grep -rn iter_canonical_hvac_zones
# custom_components/` to re-verify any time the file moves):
#   - button.py:600        — per-zone button platform setup (Bug Class #36).
#   - number.py:1541       — per-zone number platform setup (Bug Class #36).
#   - sensor.py:334        — per-zone sensor platform setup (Bug Class #36).
#   - domain_coordinators/energy.py:2567
#                          — EC's dynamic-preset evaluation loop (runtime).
#   - quality/tests/*      — fixtures / lockstep tests.
# Forbidden:
#   - custom_components/universal_room_automation/config_flow.py — any call
#     here is a Bug Class #47 violation. Regression-locked by
#     quality/tests/test_v475_d3_canonical_runtime_only.py.
#
# If a new platform needs canonical zones, add it to the allowlist above AND
# extend the D3 test's allowlist. If a UI surface needs zone metadata, derive
# it locally from `entry.options["zones"]` (see config_flow.py
# `_get_shared_thermostat_siblings` for the pattern).
# =============================================================================


def iter_canonical_hvac_zones(hass: HomeAssistant) -> list[dict]:
    """Return canonical HVAC zones (thermostat-deduplicated).

    Mirrors `ZoneManager.async_discover_zones` dedup semantics — but ONLY
    for the primary `ENTRY_TYPE_ZONE_MANAGER` path. The legacy
    `ENTRY_TYPE_ZONE` fallback at the bottom of `async_discover_zones`
    (hvac_zones.py:346) is intentionally NOT mirrored here because
    URA's canonical install (single-user policy) doesn't use it. If the
    fallback path is ever re-activated, extend this helper to cover it
    AND add a coverage test in test_v4513_1_zone_dedup.py.

    Returns a list of dicts, each with:
      - zone_id (str): matches ZoneManager's runtime assignment
        (`zone_N` derived from thermostat suffix when matchable, else
        auto-numbered with collision avoidance)
      - zone_name (str): merged display name when multiple home zones
        share a thermostat (e.g., "Entertainment + Master Suite")
      - climate_entity (str): the shared thermostat entity_id
      - ac_load_sensor (str): first non-empty among merged home zones
      - ramp_zone_enabled (bool): OR across merged home zones

    NOTE: fields that ZoneManager tracks but per-zone platform setup
    doesn't need yet (vacancy_sweep_enabled, zone_persons, zone_cameras)
    are NOT returned here. Extend the result schema if a future per-zone
    entity surface needs them — keep this helper as the single source
    of truth for "what zones exist."

    Layer 3 of the Bug Class #36 prevention strategy. See
    docs/QUALITY_CONTEXT.md "Bug Class #36: Per-Zone Entity Registration
    Bypasses ZoneManager Dedup" for the full prevention narrative.

    LOCKSTEP REQUIREMENT: any change to the merge semantics in
    `ZoneManager.async_discover_zones` (lines ~282-313) MUST be
    replicated here. The lockstep equivalence test in
    test_v4513_1_zone_dedup.py exercises both code paths against the
    same fixture and asserts identical outputs.
    """
    from ..const import (
        CONF_ENTRY_TYPE,
        CONF_ZONE_THERMOSTAT,
        ENTRY_TYPE_ZONE_MANAGER,
    )

    out: list[dict] = []
    thermostat_to_idx: dict[str, int] = {}
    assigned_ids: set[str] = set()
    next_zone_num = 0

    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ZONE_MANAGER:
            continue
        merged = {**entry.data, **entry.options}
        for zm_zone_name, zone_cfg in merged.get("zones", {}).items():
            thermostat = zone_cfg.get(CONF_ZONE_THERMOSTAT)
            if not thermostat:
                continue

            ac_load_sensor = zone_cfg.get(CONF_HVAC_AC_LOAD_SENSOR, "") or ""
            ac_ramp_zone_enabled = bool(zone_cfg.get(
                CONF_HVAC_AC_RAMP_ZONE_ENABLED,
                DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED,
            ))

            if thermostat in thermostat_to_idx:
                # Merge into existing entry (mirror ZoneManager dedup)
                existing = out[thermostat_to_idx[thermostat]]
                existing["zone_name"] = (
                    f"{existing['zone_name']} + {zm_zone_name}"
                )
                if not existing["ac_load_sensor"] and ac_load_sensor:
                    existing["ac_load_sensor"] = ac_load_sensor
                existing["ramp_zone_enabled"] = (
                    existing["ramp_zone_enabled"] or ac_ramp_zone_enabled
                )
                continue

            zone_id = _zone_id_from_thermostat_pure(
                thermostat, next_zone_num, assigned_ids,
            )
            if zone_id == f"zone_{next_zone_num}":
                next_zone_num += 1
            assigned_ids.add(zone_id)
            thermostat_to_idx[thermostat] = len(out)
            out.append({
                "zone_id": zone_id,
                "zone_name": zm_zone_name,
                "climate_entity": thermostat,
                "ac_load_sensor": ac_load_sensor,
                "ramp_zone_enabled": ac_ramp_zone_enabled,
            })

    return out

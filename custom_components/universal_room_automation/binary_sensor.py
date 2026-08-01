"""Binary sensor platform for Universal Room Automation."""
#
# Universal Room Automation vv5.44.0
# Build: 2026-01-02
# File: binary_sensor.py
# v3.2.6: Renamed "Presence" to "Sensor Presence" for clarity
#

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import (
    DOMAIN,
    VERSION,
    NAME,
    ICON_OCCUPIED,
    ICON_VACANT,
    ICON_MOTION,
    ICON_PRESENCE,
    ICON_DARK,
    ICON_ROOM_ALERT,
    STATE_OCCUPIED,
    STATE_BLE_PERSONS,
    STATE_OCCUPANCY_SOURCE,
    STATE_MOTION_DETECTED,
    STATE_PRESENCE_DETECTED,
    STATE_DARK,
    STATE_TEMPERATURE,
    STATE_HUMIDITY,
    STATE_TIME_SINCE_OCCUPIED,
    ATTR_LAST_MOTION,
    ATTR_TIMEOUT,
    CONF_DOOR_SENSORS,
    CONF_DOOR_TYPE,
    CONF_WINDOW_SENSORS,
    DOOR_TYPE_EGRESS,
    COMFORT_TEMP_MIN,
    COMFORT_TEMP_MAX,
    COMFORT_HUMIDITY_MIN,
    COMFORT_HUMIDITY_MAX,
    DEFAULT_FAN_TEMP_THRESHOLD,
    DEFAULT_HUMIDITY_THRESHOLD,
    CONF_HUMIDITY_FANS,
    CONF_HUMIDITY_FAN_THRESHOLD,
    CONF_HUMIDITY_FAN_CONTROL_ENABLED,
    DEFAULT_HUMIDITY_FAN_CONTROL_ENABLED,
    # v3.5.0 Camera Census
    CONF_CAMERA_PERSON_ENTITIES,
    CONF_ROOM_CAMERAS,
    CONF_DISABLE_CAMERA_PRESENCE,
    CONF_TRACKED_PERSONS,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ROOM,
    CONF_ENTRY_TYPE,
    # B-M4 fix-up: TIER1_KINDS moved to module-top — the prior
    # function-local imports were annotated "Bug Class #34" but that
    # class is about async_dispatcher_* function-local imports causing
    # UnboundLocalError, not plain constants. Hoisting to module-top
    # both eliminates the misleading comment AND drops 4 redundant
    # function-local imports.
    TIER1_KINDS,
)
from .aggregation import AggregationEntity
from .coordinator import UniversalRoomCoordinator
from .entity import UniversalRoomEntity

_LOGGER = logging.getLogger(__name__)


# G1: per-room control-list attrs helper lives in a HA-import-free
# module so it can be unit-tested without stubbing homeassistant.
# It reads the six actuator-driving CONF lists via
# `coordinator._get_config` — the SAME options-first-with-data-fallback
# read path `coordinator.py:820-840` uses for actuation — so the
# emitted attrs cannot diverge from the actuator's ground truth.
from .binary_sensor_control_attrs import build_control_attrs as _build_control_attrs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Universal Room Automation binary sensors."""
    from .const import (
        CONF_ENTRY_TYPE, ENTRY_TYPE_INTEGRATION, ENTRY_TYPE_ZONE,
        ENTRY_TYPE_ZONE_MANAGER, ENTRY_TYPE_COORDINATOR_MANAGER,
    )

    # Check if this is an integration entry (aggregation binary sensors)
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_INTEGRATION:
        from .aggregation import async_setup_aggregation_binary_sensors
        await async_setup_aggregation_binary_sensors(hass, entry, async_add_entities)

        # v3.5.0: Census binary sensors for integration entry
        census_binary: list = [
            URAUnexpectedPersonSensor(hass, entry),
            # v3.5.2: Census mismatch sensor
            CensusMismatchSensor(hass, entry),
        ]

        # v3.5.2: Per-person phone-left-behind sensor (one per tracked person)
        from .const import CONF_TRACKED_PERSONS
        merged_config = {**entry.data, **entry.options}
        tracked_person_entities = merged_config.get(CONF_TRACKED_PERSONS, [])
        for entity_id in tracked_person_entities:
            if entity_id.startswith("person."):
                person_name = entity_id.replace("person.", "").replace("_", " ").title()
            else:
                person_name = entity_id.replace("_", " ").title()
            census_binary.append(PersonPhoneLeftBehindSensor(hass, entry, person_name))

        async_add_entities(census_binary)
        return

    # v3.6.0: Zone Manager entry - set up zone binary sensors under this entry
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE_MANAGER:
        from .aggregation import async_setup_zone_manager_binary_sensors
        await async_setup_zone_manager_binary_sensors(hass, entry, async_add_entities)
        return

    # v3.6.0: Coordinator Manager entry — Presence + Safety binary sensors
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
        coordinator_binary = [
            HouseOccupiedBinarySensor(hass, entry),
            HouseSleepingBinarySensor(hass, entry),
            GuestModeBinarySensor(hass, entry),
            # v3.6.0-c2: Safety Coordinator
            SafetyAlertBinarySensor(hass, entry),
            # v3.6.0.3: Glanceable safety binary sensors
            SafetyWaterLeakBinarySensor(hass, entry),
            SafetyAirQualityBinarySensor(hass, entry),
            # v3.6.0-c3: Security Coordinator
            SecurityAlertBinarySensor(hass, entry),
            # v3.6.29: Notification Manager
            NMActiveAlertBinarySensor(hass, entry),
            # v3.7.3: Energy Coordinator
            EnergyEnvoyAvailableBinarySensor(hass, entry),
            # v3.7.7: L1 Charger status
            EnergyL1ChargerBinarySensor(hass, entry),
            # v4.7.x D2: EC sub-switch sync health sensor
            ECSubSwitchesSyncedSensor(hass, entry),
            # v4.7.x Cycle A: WeatherProviderManager divergence flag
            WeatherDivergenceBinarySensor(hass, entry),
        ]
        # v4.7.8 D5: per-canonical-HVAC-zone egress window open rollup sensor.
        try:
            from .domain_coordinators.hvac_zones import iter_canonical_hvac_zones
            for _z in iter_canonical_hvac_zones(hass):
                coordinator_binary.append(
                    HVACZoneEgressWindowOpenSensor(
                        hass, entry, _z["zone_id"], _z["zone_name"],
                    )
                )
        except Exception:
            # v4.7.8 fix-up C-M3: WARNING (was debug) so silent enumeration
            # failures during initial install surface in normal logs. No
            # per-zone egress sensors get created on this code path failure.
            _LOGGER.warning(
                "v4.7.8: canonical zone enumeration for egress sensors failed",
                exc_info=True,
            )
        async_add_entities(coordinator_binary)
        return

    # Legacy zone entry - no longer creates sensors
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
        return

    # Room entry - normal binary sensor setup
    coordinator: UniversalRoomCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Core binary sensors (enabled by default)
    entities = [
        OccupiedBinarySensor(coordinator),
        MotionDetectedBinarySensor(coordinator),
        PresenceDetectedBinarySensor(coordinator),
        DarkBinarySensor(coordinator),
        # v3.5.0: Per-room camera person detected sensor
        CameraPersonDetectedSensor(coordinator),
    ]

    # Phase 4 diagnostic binary sensors (disabled by default)
    entities.extend([
        HVACCoordinatedBinarySensor(coordinator),
        EnergySavingActiveBinarySensor(coordinator),
        FanShouldRunBinarySensor(coordinator),
        # D6 — humidity-fan visibility sensors (bathroom-exhaust intelligence cycle).
        HumidityFanShouldRunBinarySensor(coordinator),
        HumidityFanActiveBinarySensor(coordinator),
        HVACCoolingBinarySensor(coordinator),
        HVACHeatingBinarySensor(coordinator),
        RoomAlertBinarySensor(coordinator),
        # v3.12.0 M2: Automation conflict detection (populated in M3)
        AutomationConflictBinarySensor(coordinator),
        # v4.0.0-B2: Bayesian occupancy anomaly
        OccupancyAnomalyBinarySensor(coordinator),
        # v4.7.8 D5: per-room egress window open (reads room's window_sensor
        # state through coordinator config — graceful no-op when window_sensor
        # unset for this room).
        RoomEgressWindowOpenSensor(coordinator),
        # Fan-noise Mode-2: per-room "recheck in progress" diagnostic.
        # Always registered (disabled-by-default) so operators can flip
        # opt-in rooms without a config-flow round-trip. is_on reads
        # FanRecheckManager.get_room_attrs each access.
        RoomFanRecheckInProgressSensor(coordinator),
    ])

    async_add_entities(entities)
    _LOGGER.info(
        "Set up %d binary sensors for room: %s",
        len(entities),
        entry.data.get("room_name")
    )


class OccupiedBinarySensor(UniversalRoomEntity, BinarySensorEntity, RestoreEntity):
    """Binary sensor for room occupancy.

    v3.20.0: Inherits RestoreEntity to persist critical coordinator state
    across HA restarts (became_occupied_time, failsafe_fired, etc.).
    """

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "occupied", "Occupied")

    async def async_added_to_hass(self) -> None:
        """Restore critical coordinator state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()

        # Review fix: fall back to DB if RestoreEntity state unavailable
        if last_state is None or last_state.attributes is None:
            await self._restore_from_db_fallback()
            return

        attrs = last_state.attributes

        # Restore critical coordinator state
        if became_time := attrs.get("became_occupied_time"):
            try:
                self.coordinator._became_occupied_time = dt_util.parse_datetime(
                    became_time
                )
            except (ValueError, TypeError):
                pass

        if attrs.get("last_occupied_state") is not None:
            self.coordinator._last_occupied_state = bool(
                attrs["last_occupied_state"]
            )

        if first_detected := attrs.get("occupancy_first_detected"):
            try:
                self.coordinator._occupancy_first_detected = dt_util.parse_datetime(
                    first_detected
                )
            except (ValueError, TypeError):
                pass

        if attrs.get("failsafe_fired") is not None:
            self.coordinator._failsafe_fired = bool(attrs["failsafe_fired"])

        # Nice-to-have restores
        if trigger_source := attrs.get("last_trigger_source"):
            self.coordinator._last_trigger_source = trigger_source

        if lux_zone := attrs.get("last_lux_zone"):
            self.coordinator._last_lux_zone = lux_zone

        # Cover daily dedup
        if hasattr(self.coordinator, "automation") and self.coordinator.automation:
            if open_date := attrs.get("last_timed_open_date"):
                self.coordinator.automation._last_timed_open_date = open_date
            if close_date := attrs.get("last_timed_close_date"):
                self.coordinator.automation._last_timed_close_date = close_date

        room_name = self.coordinator.entry.data.get("room_name", "Unknown")
        _LOGGER.info(
            "Room %s: Restored occupancy state "
            "(was_occupied=%s, session_start=%s, failsafe=%s)",
            room_name,
            self.coordinator._last_occupied_state,
            self.coordinator._became_occupied_time,
            self.coordinator._failsafe_fired,
        )

    async def _restore_from_db_fallback(self) -> None:
        """Restore coordinator state from room_state DB table.

        Called when RestoreEntity state is unavailable (fresh install,
        corrupted storage, etc.). This is the crash-resilience path.
        """
        from .const import DOMAIN
        db = self.hass.data.get(DOMAIN, {}).get("database")
        if not db:
            return
        room_id = self.coordinator.entry.entry_id
        row = await db.get_room_state(room_id)
        if row is None:
            return

        room_name = self.coordinator.entry.data.get("room_name", "Unknown")

        if became_time := row.get("became_occupied_time"):
            try:
                self.coordinator._became_occupied_time = dt_util.parse_datetime(
                    became_time
                )
            except (ValueError, TypeError):
                pass

        if row.get("last_occupied_state") is not None:
            self.coordinator._last_occupied_state = bool(row["last_occupied_state"])

        if first_detected := row.get("occupancy_first_detected"):
            try:
                self.coordinator._occupancy_first_detected = dt_util.parse_datetime(
                    first_detected
                )
            except (ValueError, TypeError):
                pass

        if row.get("failsafe_fired") is not None:
            self.coordinator._failsafe_fired = bool(row["failsafe_fired"])

        if trigger_source := row.get("last_trigger_source"):
            self.coordinator._last_trigger_source = trigger_source

        if lux_zone := row.get("last_lux_zone"):
            self.coordinator._last_lux_zone = lux_zone

        if hasattr(self.coordinator, "automation") and self.coordinator.automation:
            if open_date := row.get("last_timed_open_date"):
                self.coordinator.automation._last_timed_open_date = open_date
            if close_date := row.get("last_timed_close_date"):
                self.coordinator.automation._last_timed_close_date = close_date

        _LOGGER.info(
            "Room %s: Restored from DB fallback "
            "(was_occupied=%s, session_start=%s)",
            room_name,
            self.coordinator._last_occupied_state,
            self.coordinator._became_occupied_time,
        )

    @property
    def is_on(self) -> bool:
        """Return true if room is occupied."""
        return self.coordinator.data.get(STATE_OCCUPIED, False) if self.coordinator.data else False

    @property
    def icon(self) -> str:
        """Return icon based on state."""
        return ICON_OCCUPIED if self.is_on else ICON_VACANT

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional state attributes."""
        attrs = {
            ATTR_LAST_MOTION: self.coordinator._last_motion_time.isoformat()
            if self.coordinator._last_motion_time else None,
            ATTR_TIMEOUT: self.coordinator.data.get("timeout_remaining", 0) if self.coordinator.data else 0,
            # Persisted state for restart resilience
            "became_occupied_time": self.coordinator._became_occupied_time.isoformat()
            if self.coordinator._became_occupied_time else None,
            "last_occupied_state": self.coordinator._last_occupied_state,
            "occupancy_first_detected": self.coordinator._occupancy_first_detected.isoformat()
            if self.coordinator._occupancy_first_detected else None,
            "failsafe_fired": self.coordinator._failsafe_fired,
            "last_trigger_source": self.coordinator._last_trigger_source,
            "last_lux_zone": self.coordinator._last_lux_zone,
        }
        if self.coordinator.data:
            attrs["occupancy_source"] = self.coordinator.data.get(
                STATE_OCCUPANCY_SOURCE, "none"
            )
            attrs["ble_persons"] = self.coordinator.data.get(
                STATE_BLE_PERSONS, []
            )
        # Cover daily dedup from automation
        if hasattr(self.coordinator, "automation") and self.coordinator.automation:
            attrs["last_timed_open_date"] = (
                self.coordinator.automation._last_timed_open_date
            )
            attrs["last_timed_close_date"] = (
                self.coordinator.automation._last_timed_close_date
            )
        # v4.6.11 D4.3: idle_duration — seconds since room was last occupied.
        # Zero when occupied, STATE_TIME_SINCE_OCCUPIED when vacant.
        try:
            if self.is_on:
                attrs["idle_duration"] = 0
            else:
                attrs["idle_duration"] = (
                    self.coordinator.data.get(STATE_TIME_SINCE_OCCUPIED)
                    if self.coordinator.data else None
                )
        except Exception:
            attrs["idle_duration"] = None
        # v4.6.11 D4.4: current_persons — list of person names tracked in this room.
        # Returns [] not None (UI expects array — Bug Class #8).
        # Reads from person_coordinator registered under hass.data[DOMAIN]["person_coordinator"].
        try:
            _persons: list[str] = []
            _pc = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
            if _pc is not None:
                _room_name = self.coordinator.entry.data.get("room_name", "")
                if _room_name:
                    _persons = _pc.get_room_occupants(_room_name) or []
            attrs["current_persons"] = _persons
        except Exception:
            attrs["current_persons"] = []
        # Provenance-split cycle (D5): per-room Tier-1 provenance + fan
        # diagnostic attrs. Sourced from the zone tracker owning this
        # room. Lazy reads — no RestoreEntity coupling — fresh per
        # `_run_inference` tick.
        try:
            # B-M4 fix-up: TIER1_KINDS imported at module top.
            _room_name = self.coordinator.entry.data.get("room_name", "")
            _tier1_default = {k: False for k in TIER1_KINDS}
            _provenance = dict(_tier1_default)
            _last_kind = ""
            _fan_on = False
            _suspect = False
            _manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            _presence = _manager.coordinators.get("presence") if _manager else None
            if _presence is not None and _room_name:
                # C2 fix-up: O(1) tracker lookup via the room->zone
                # reverse cache populated at _discover_zones. Replaces
                # the prior per-attr-access walk over all zone trackers
                # (was O(N_zones x N_rooms_per_zone) per access per
                # sensor; degenerates on a Zone-Manager reload that
                # spreads N rooms across the same N trackers).
                _tracker = None
                if hasattr(_presence, "tracker_for_room"):
                    _tracker = _presence.tracker_for_room(_room_name)
                else:
                    # Pre-fix-up presence build — keep the legacy walk
                    # so the binary_sensor surface stays robust against
                    # version-skew during the first restart after the
                    # cycle lands.
                    for _t in getattr(_presence, "zone_trackers", {}).values():
                        if _room_name in _t.room_names:
                            _tracker = _t
                            break
                if _tracker is not None:
                    if hasattr(_tracker, "provenance_for"):
                        _provenance = _tracker.provenance_for(_room_name)
                    _last_kind = getattr(
                        _tracker, "_last_kind_per_room", {},
                    ).get(_room_name, "")
                    _fan_on = _room_name in (
                        getattr(_tracker, "_fan_on_rooms", set()) or set()
                    )
                    _inputs = (
                        getattr(_presence, "_signal_consensus_inputs", {}) or {}
                    )
                    _suspect = _room_name in (
                        _inputs.get("fan_interference_rooms", []) or []
                    )
            attrs["tier1_provenance"] = _provenance
            attrs["last_kind_to_fire"] = _last_kind
            attrs["fan_on"] = _fan_on
            attrs["fan_interference_suspect"] = _suspect
            # Presence batch D3: sibling attr — the entity_id whose edge
            # last dispatched into this room's Tier-1 substrate. Empty
            # string when the substrate isn't ready or no edge has
            # dispatched. Read-only diagnostic (invariant I-D3).
            _last_edge_entity = ""
            try:
                _substrate = (
                    getattr(_presence, "_substrate", None)
                    if _presence is not None else None
                )
                if _substrate is not None and _room_name:
                    _last_edge_entity = _substrate.last_edge_entity_for(
                        _room_name,
                    ) or ""
            except Exception:  # noqa: BLE001 — defensive
                _last_edge_entity = ""
            attrs["last_edge_entity"] = _last_edge_entity
            # Fan-noise mitigation D1 (Layer-1 silent gate) attrs.
            # Hold-active = True when the derived `_room_occupied`
            # view for this room is being EXTENDED by the gate (the
            # natural OR has already gone False; the hold is what's
            # keeping it True). hold_expires_at_iso surfaces the
            # decay deadline for operator visibility. ble_corroboration
            # _layer names the strongest non-fired BLE layer label
            # (L1 / L2 / L3 / none) — only meaningful for suspect rooms.
            _hold_active = False
            _hold_iso: str | None = None
            _ladder_label = "none"
            try:
                if _tracker is not None:
                    _hold_until = getattr(
                        _tracker, "_fan_interference_hold_until", {},
                    ).get(_room_name)
                    if _hold_until is not None:
                        from homeassistant.util import dt as _dt_util
                        _now = _dt_util.utcnow()
                        if _hold_until > _now:
                            # Hold-active iff hold is in the future AND
                            # provenance is otherwise empty (the hold is
                            # what's keeping the room True). If any
                            # provenance kind is True the OR is doing
                            # the work, not the hold.
                            _hold_iso = _hold_until.isoformat()
                            _hold_active = not any(
                                bool(v) for v in (_provenance or {}).values()
                            )
                if _presence is not None:
                    _ladder_label = (_inputs.get(
                        "fan_interference_ladder", {}
                    ) or {}).get(_room_name, "none")
            except Exception:
                _hold_active = False
                _hold_iso = None
                _ladder_label = "none"
            attrs["fan_interference_hold_active"] = _hold_active
            attrs["fan_interference_hold_expires_at"] = _hold_iso
            attrs["ble_corroboration_layer"] = _ladder_label
            # D7 observability (mmwave-corroboration Tier-3, D3):
            # per-room comfort-fan house-AWAY veto count. Defensively
            # 0 if the helper module hasn't been imported yet.
            try:
                from .fan_veto import get_veto_count  # noqa: PLC0415
                attrs["comfort_fan_away_veto_count"] = get_veto_count(
                    self.hass, _room_name,
                )
            except Exception:  # noqa: BLE001 — never fail attr expansion
                attrs["comfort_fan_away_veto_count"] = 0
            # Tier-3 D2 mmWave fan-corroboration demotion — observability.
            # Read directly off the room coordinator's per-tick counters
            # (parsimony — attrs only, no new entities). Defaults keep
            # the surface stable for rooms whose coord hasn't ticked yet.
            try:
                attrs["mmwave_fan_demoted"] = bool(
                    getattr(
                        self.coordinator,
                        "_mmwave_fan_demoted_last_tick",
                        False,
                    )
                )
                attrs["mmwave_fan_demotions_since_boot"] = int(
                    getattr(
                        self.coordinator,
                        "_mmwave_fan_demotions_since_boot",
                        0,
                    )
                )
            except Exception:  # noqa: BLE001 — never fail attr expansion
                attrs["mmwave_fan_demoted"] = False
                attrs["mmwave_fan_demotions_since_boot"] = 0
        except Exception:
            # B-M4 fix-up: TIER1_KINDS imported at module top.
            attrs["tier1_provenance"] = {k: False for k in TIER1_KINDS}
            attrs["last_kind_to_fire"] = ""
            attrs["last_edge_entity"] = ""
            attrs["fan_on"] = False
            attrs["fan_interference_suspect"] = False
            attrs["fan_interference_hold_active"] = False
            attrs["fan_interference_hold_expires_at"] = None
            attrs["ble_corroboration_layer"] = "none"
            attrs["comfort_fan_away_veto_count"] = 0
            attrs["mmwave_fan_demoted"] = False
            attrs["mmwave_fan_demotions_since_boot"] = 0
        # Fan-noise Mode-2 (room-tier fan-pause + clean recheck) attrs.
        # Sourced from FanRecheckManager.get_room_attrs(room_name); the
        # manager owns idempotent defaults for rooms it has not yet
        # seen (idle / None / "none"). Lazy lookup — survives the case
        # where presence has not finished setup yet.
        try:
            _fr_state = "idle"
            _fr_last_outcome = None
            _fr_last_attempt_iso = None
            _fr_layer = "none"
            _manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            _presence = (
                _manager.coordinators.get("presence") if _manager else None
            )
            _fr_mgr = (
                getattr(_presence, "_fan_recheck_manager", None)
                if _presence is not None else None
            )
            _room_name = self.coordinator.entry.data.get("room_name", "")
            if _fr_mgr is not None and _room_name:
                _fr_attrs = _fr_mgr.get_room_attrs(_room_name) or {}
                _fr_state = _fr_attrs.get("fan_recheck_state", "idle")
                _fr_last_outcome = _fr_attrs.get("fan_recheck_last_outcome")
                _fr_last_attempt_iso = _fr_attrs.get(
                    "fan_recheck_last_attempt_iso",
                )
                _fr_layer = _fr_attrs.get(
                    "fan_recheck_ble_ladder_layer", "none",
                )
            attrs["fan_recheck_state"] = _fr_state
            attrs["fan_recheck_last_outcome"] = _fr_last_outcome
            attrs["fan_recheck_last_attempt_iso"] = _fr_last_attempt_iso
            attrs["fan_recheck_ble_ladder_layer"] = _fr_layer
        except Exception:
            attrs["fan_recheck_state"] = "idle"
            attrs["fan_recheck_last_outcome"] = None
            attrs["fan_recheck_last_attempt_iso"] = None
            attrs["fan_recheck_ble_ladder_layer"] = "none"
        # Occupancy substrate unification cycle (D7): lazy diagnostic attr
        # surfacing the substrate's per-room, per-kind raw-signal view
        # for THIS room at the last tick. Sourced from the
        # PresenceCoordinator-owned OccupancySubstrate via the same
        # data path used by `tier1_provenance` above — but read from
        # the substrate directly (instead of from
        # `_room_provenance`) so the substrate's CONF-driven truth is
        # surfaced even before the zone tier has fanned an edge into
        # the tracker. Defaults to the same {motion/mmwave/occupancy:
        # False} shape on any error so HA dev-tools never sees a
        # missing key.
        try:
            # B-M4 fix-up: TIER1_KINDS imported at module top.
            _sub_kinds = {k: False for k in TIER1_KINDS}
            _room_name = self.coordinator.entry.data.get("room_name", "")
            _manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            _presence = _manager.coordinators.get("presence") if _manager else None
            _substrate = (
                getattr(_presence, "_substrate", None)
                if _presence is not None else None
            )
            if _substrate is not None and _room_name:
                try:
                    _sub_kinds = _substrate.get_room_kinds(_room_name)
                except Exception:
                    pass
            attrs["substrate_kinds"] = _sub_kinds
        except Exception:
            # B-M4 fix-up: TIER1_KINDS imported at module top.
            attrs["substrate_kinds"] = {k: False for k in TIER1_KINDS}
        # G1: per-room control-list attrs — read-only projection of the
        # actuator-driving CONF lists via `coordinator._get_config` so
        # the PWA (and any consumer) reads the same truth URA actuates on.
        # See `_build_control_attrs` at module top for per-key defaults.
        try:
            attrs.update(_build_control_attrs(self.coordinator))
        except Exception:  # noqa: BLE001 — never let G1 blank the whole dict
            attrs.setdefault("control_lights", [])
            attrs.setdefault("control_night_lights", [])
            attrs.setdefault("control_fans", [])
            attrs.setdefault("control_humidity_fans", [])
            attrs.setdefault("control_covers", [])
            attrs.setdefault("control_climate_entity", None)
        return attrs


class MotionDetectedBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for motion detection."""

    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_icon = ICON_MOTION

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "motion", "Motion")

    @property
    def is_on(self) -> bool:
        """Return true if motion is detected."""
        return self.coordinator.data.get(STATE_MOTION_DETECTED, False) if self.coordinator.data else False


class PresenceDetectedBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for presence detection (mmWave/PIR/combined)."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = ICON_PRESENCE

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        # v3.2.6: Renamed from "Presence" to "Sensor Presence" for clarity
        # Works with mmWave, PIR, or combined presence sensors
        # unique_id kept as "presence" for backward compatibility
        super().__init__(coordinator, "presence", "Sensor Presence")

    @property
    def is_on(self) -> bool:
        """Return true if presence is detected."""
        return self.coordinator.data.get(STATE_PRESENCE_DETECTED, False) if self.coordinator.data else False


class DarkBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for dark state."""

    _attr_icon = ICON_DARK

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "dark", "Dark")

    @property
    def is_on(self) -> bool:
        """Return true if room is dark."""
        return self.coordinator.data.get(STATE_DARK, False) if self.coordinator.data else False


class HVACCoordinatedBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for HVAC coordination status."""

    _attr_icon = "mdi:hvac"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "hvac_coordinated", "HVAC Coordinated")

    @property
    def available(self) -> bool:
        """Sensor is always available."""
        return True

    @property
    def is_on(self) -> bool:
        """Return true if HVAC is coordinating with room automation."""
        return self.coordinator.data.get("hvac_coordinated", False) if self.coordinator.data else False


class EnergySavingActiveBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for energy saving mode status."""

    _attr_icon = "mdi:leaf"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "energy_saving_active", "Energy Saving Active")

    @property
    def available(self) -> bool:
        """Sensor is always available."""
        return True

    @property
    def is_on(self) -> bool:
        """Return true if energy saving mode is active."""
        # Energy saving when room vacant and devices still consuming power
        occupied = self.coordinator.data.get(STATE_OCCUPIED, False) if self.coordinator.data else False
        power = self.coordinator.data.get("power_current", 0) if self.coordinator.data else 0
        return not occupied and power > 5  # Idle power threshold


class FanShouldRunBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Comfort-fan run recommendation (temp-driven).

    D6 (bathroom-exhaust intelligence cycle): renamed display to
    "Comfort Fan Should Run" to disambiguate from the new humidity-fan
    sensor below. Entity ID + unique ID unchanged (only `_attr_name`).
    Logic is comfort-only — reads `fan_temp_threshold`, not humidity.
    """

    _attr_icon = "mdi:fan"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "fan_should_run", "Comfort Fan Should Run")

    @property
    def available(self) -> bool:
        """Available if temperature data exists."""
        return (self.coordinator.data and self.coordinator.data.get(STATE_TEMPERATURE)) is not None

    @property
    def is_on(self) -> bool:
        """Return true if fan should be running based on logic."""
        temp = self.coordinator.data.get(STATE_TEMPERATURE) if self.coordinator.data else None
        occupied = self.coordinator.data.get(STATE_OCCUPIED, False) if self.coordinator.data else False
        if temp is None or not occupied:
            return False
        
        fan_threshold = self.coordinator.entry.data.get("fan_temp_threshold", 80)
        return temp >= fan_threshold


class HumidityFanShouldRunBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """D6 — humidity-fan run recommendation.

    True iff the room-path logic WOULD turn the humidity fan on right now
    (humidity ≥ threshold, NOT cap-suppressed, NOT toggle-#3 disabled).
    Spike-trigger surface is intentionally NOT consulted here (this sensor
    is the absolute-threshold + suppression + toggle view; the fan
    actually running is HumidityFanActiveBinarySensor below).
    """

    _attr_icon = "mdi:fan-alert"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        super().__init__(
            coordinator, "humidity_fan_should_run", "Humidity Fan Should Run",
        )

    @property
    def available(self) -> bool:
        merged = {
            **self.coordinator.entry.data,
            **self.coordinator.entry.options,
        }
        return bool(merged.get(CONF_HUMIDITY_FANS))

    @property
    def is_on(self) -> bool:
        merged = {
            **self.coordinator.entry.data,
            **self.coordinator.entry.options,
        }
        if not merged.get(CONF_HUMIDITY_FANS):
            return False
        if not merged.get(
            CONF_HUMIDITY_FAN_CONTROL_ENABLED, DEFAULT_HUMIDITY_FAN_CONTROL_ENABLED,
        ):
            return False
        humidity = (
            self.coordinator.data.get(STATE_HUMIDITY)
            if self.coordinator.data else None
        )
        if humidity is None:
            return False
        # Cap-suppressed → fan must stay off until humidity drops below OFF.
        automation = getattr(self.coordinator, "automation", None)
        if automation is not None and getattr(
            automation, "_humidity_cap_suppressed", False,
        ):
            return False
        threshold = float(
            merged.get(CONF_HUMIDITY_FAN_THRESHOLD, DEFAULT_HUMIDITY_THRESHOLD)
        )
        return float(humidity) >= threshold


class HumidityFanActiveBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """D6 — humidity-fan controller-active state.

    True iff the room-tier controller is actively driving the humidity fan
    (anchor set). Distinct from "physically on": if an operator turned the
    fan on manually with the controller idle, this reads False.
    """

    _attr_icon = "mdi:fan-clock"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        super().__init__(
            coordinator, "humidity_fan_active", "Humidity Fan Active",
        )

    @property
    def available(self) -> bool:
        merged = {
            **self.coordinator.entry.data,
            **self.coordinator.entry.options,
        }
        return bool(merged.get(CONF_HUMIDITY_FANS))

    @property
    def is_on(self) -> bool:
        automation = getattr(self.coordinator, "automation", None)
        if automation is None:
            return False
        return getattr(automation, "_humidity_fan_triggered_time", None) is not None


class HVACCoolingBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for HVAC cooling status."""

    _attr_device_class = BinarySensorDeviceClass.COLD
    _attr_icon = "mdi:snowflake"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "hvac_cooling", "HVAC Cooling")

    @property
    def available(self) -> bool:
        """Available if climate entity is configured."""
        climate_entity = self.coordinator.entry.data.get("climate_entity")
        if not climate_entity:
            return False
        state = self.coordinator.hass.states.get(climate_entity)
        return state is not None

    @property
    def is_on(self) -> bool:
        """Return true if HVAC is actively cooling."""
        climate_entity = self.coordinator.entry.data.get("climate_entity")
        if not climate_entity:
            return False
        
        state = self.coordinator.hass.states.get(climate_entity)
        if not state:
            return False
        
        hvac_action = state.attributes.get("hvac_action")
        return hvac_action == "cooling"


class HVACHeatingBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for HVAC heating status."""

    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_icon = "mdi:fire"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "hvac_heating", "HVAC Heating")

    @property
    def available(self) -> bool:
        """Available if climate entity is configured."""
        climate_entity = self.coordinator.entry.data.get("climate_entity")
        if not climate_entity:
            return False
        state = self.coordinator.hass.states.get(climate_entity)
        return state is not None

    @property
    def is_on(self) -> bool:
        """Return true if HVAC is actively heating."""
        climate_entity = self.coordinator.entry.data.get("climate_entity")
        if not climate_entity:
            return False
        
        state = self.coordinator.hass.states.get(climate_entity)
        if not state:
            return False
        
        hvac_action = state.attributes.get("hvac_action")
        return hvac_action == "heating"


class RoomAlertBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Binary sensor for room alert/alarm status."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = ICON_ROOM_ALERT

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "room_alert", "Room Alert")

    @property
    def is_on(self) -> bool:
        """Return true if any alerts active."""
        alerts = self._get_active_alerts()
        return len(alerts) > 0

    @property
    def extra_state_attributes(self) -> dict:
        """Return alert details."""
        alerts = self._get_active_alerts()
        return {
            "alert_count": len(alerts),
            "alerts": alerts,
            "temperature_alert": self._check_temperature_alert(),
            "humidity_alert": self._check_humidity_alert(),
            "door_alert": self._check_door_alert(),
            "window_alert": self._check_window_alert(),
        }

    def _get_active_alerts(self) -> list[str]:
        """Get list of active alert descriptions."""
        alerts = []

        # Temperature alerts - use existing thresholds
        temp = self.coordinator.data.get(STATE_TEMPERATURE) if self.coordinator.data else None
        if temp:
            if temp > DEFAULT_FAN_TEMP_THRESHOLD:
                alerts.append(f"Temperature too high: {temp:.1f}°F")
            elif temp < COMFORT_TEMP_MIN:
                alerts.append(f"Temperature too low: {temp:.1f}°F")

        # Humidity alerts - use existing thresholds
        humidity = self.coordinator.data.get(STATE_HUMIDITY) if self.coordinator.data else None
        if humidity:
            if humidity > DEFAULT_HUMIDITY_THRESHOLD:
                alerts.append(f"Humidity too high: {humidity:.0f}%")
            elif humidity < COMFORT_HUMIDITY_MIN:
                alerts.append(f"Humidity too low: {humidity:.0f}%")

        # Door alert (if egress type)
        if self._check_door_alert():
            door_sensor = self.coordinator.entry.data.get(CONF_DOOR_SENSORS)
            if door_sensor:
                door_state = self.hass.states.get(door_sensor)
                if door_state and door_state.state == "on":
                    last_changed = door_state.last_changed
                    duration = int((dt_util.now() - last_changed).total_seconds() / 60)
                    alerts.append(f"Egress door open for {duration} minutes")

        # Window alert
        if self._check_window_alert():
            window_sensor = self.coordinator.entry.data.get(CONF_WINDOW_SENSORS)
            if window_sensor:
                window_state = self.hass.states.get(window_sensor)
                if window_state and window_state.state == "on":
                    last_changed = window_state.last_changed
                    duration = int((dt_util.now() - last_changed).total_seconds() / 60)
                    alerts.append(f"Window open for {duration} minutes")

        return alerts

    def _check_temperature_alert(self) -> bool:
        """Check if temperature is outside safe range."""
        temp = self.coordinator.data.get(STATE_TEMPERATURE) if self.coordinator.data else None
        if temp is None:
            return False
        return temp > DEFAULT_FAN_TEMP_THRESHOLD or temp < COMFORT_TEMP_MIN

    def _check_humidity_alert(self) -> bool:
        """Check if humidity is outside safe range."""
        humidity = self.coordinator.data.get(STATE_HUMIDITY) if self.coordinator.data else None
        if humidity is None:
            return False
        return humidity > DEFAULT_HUMIDITY_THRESHOLD or humidity < COMFORT_HUMIDITY_MIN

    def _check_door_alert(self) -> bool:
        """Check if egress door has been open too long."""
        door_sensor = self.coordinator.entry.data.get(CONF_DOOR_SENSORS)
        door_type = self.coordinator.entry.data.get(CONF_DOOR_TYPE)
        
        if not door_sensor or door_type != DOOR_TYPE_EGRESS:
            return False
        
        door_state = self.hass.states.get(door_sensor)
        if not door_state or door_state.state != "on":
            return False
        
        # Check if open for more than 10 minutes
        last_changed = door_state.last_changed
        duration = (dt_util.now() - last_changed).total_seconds() / 60
        return duration > 10

    def _check_window_alert(self) -> bool:
        """Check if window has been open too long."""
        window_sensor = self.coordinator.entry.data.get(CONF_WINDOW_SENSORS)
        
        if not window_sensor:
            return False
        
        window_state = self.hass.states.get(window_sensor)
        if not window_state or window_state.state != "on":
            return False
        
        # Check if open for more than 30 minutes
        last_changed = window_state.last_changed
        duration = (dt_util.now() - last_changed).total_seconds() / 60
        return duration > 30


# ============================================================================
# v3.12.0 M2: AUTOMATION CONFLICT BINARY SENSOR
# ============================================================================


class AutomationConflictBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Detects when AI rules and URA built-in automation target the same entity.

    Reads _conflict_detected and _last_conflicts from the room coordinator.
    Conflict detection runs in coordinator._detect_ai_rule_conflicts() during
    AI rule execution (M3). Turns on when an AI rule targets the same entity
    as URA's built-in automation for the same trigger.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-decagram"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "automation_conflict", "Automation Conflict")

    @property
    def is_on(self) -> bool:
        """Return true if any conflicts detected."""
        return getattr(self.coordinator, "_conflict_detected", False)

    @property
    def extra_state_attributes(self) -> dict:
        """Return conflict details."""
        conflicts = getattr(self.coordinator, "_last_conflicts", [])
        return {
            "conflict_count": len(conflicts),
            "last_conflicts": conflicts[-5:] if conflicts else [],
        }


# ============================================================================
# v3.5.0: CENSUS BINARY SENSORS
# ============================================================================


class CameraPersonDetectedSensor(UniversalRoomEntity, BinarySensorEntity):
    """Per-room binary sensor: true when any fused camera source sees a person.

    2026-08-01 fusion rewrite: reads NEW room key CONF_ROOM_CAMERAS (D1),
    resolves via CameraResolver (D2), and OR-fuses the resolved per-integration
    person binary_sensors with per-source attribution + agreement/confidence
    attrs.

    - Respects CONF_DISABLE_CAMERA_PRESENCE (forces off; disabled_by_config).
    - Empty CONF_ROOM_CAMERAS -> is_on=False (not unavailable).
    - Falsifiable invariant (Review D): is_on iff any resolved source == "on".
    """

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:camera-account"

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "camera_person_detected", "Camera Person Detected")
        # Fix #7: fusion is now a LIST of RoomCameraFusion (one per physical camera).
        self._fusions: list | None = None
        self._source_entity_ids: list[str] = []
        self._unsub_state = None
        self._unsub_lifecycle = None

    # Fix #5 (A-M2/B-MED-1): use HA slugify for the fused entity_id derivation
    # (via the base class default). Keep the resolver-derived object_id stable
    # across renames by relying on unique_id from super().__init__.

    def _get_fusion(self):
        """Return list[RoomCameraFusion] for this room's configured cameras.

        Lazily resolves on first read; cached on the entity, re-resolved on
        the room entry's lifecycle signal (A-M1/E-MED-1 cache invalidation).
        """
        if self._fusions is not None:
            return self._fusions
        try:
            from .camera_resolver import CameraResolver  # noqa: PLC0415
            from homeassistant.helpers import (  # noqa: PLC0415
                entity_registry as er, device_registry as dr,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "CameraPersonDetectedSensor: resolver import failed: %s", exc
            )
            return None
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        room_cams = config.get(CONF_ROOM_CAMERAS, []) or []
        if not room_cams:
            # Fix #5 warn-once when a covered-by-config room resolves to None.
            _LOGGER.debug(
                "CameraPersonDetectedSensor(%s): CONF_ROOM_CAMERAS empty",
                self.coordinator.entry.title,
            )
            return None
        try:
            resolver = CameraResolver(
                er.async_get(self.hass),
                dr.async_get(self.hass),
                state_getter=self.hass.states.get,
            )
            self._fusions = resolver.resolve_operator_declaration(room_cams)
            self._source_entity_ids = [
                eid for f in self._fusions for eid in f.person_binary_sensor_entity_ids()
            ]
            total_sources = sum(len(f.sources) for f in self._fusions)
            _LOGGER.info(
                "CameraPersonDetectedSensor(%s): resolved %d cameras / %d sources "
                "from %d configured entities: %s",
                self.coordinator.entry.title, len(self._fusions), total_sources,
                len(room_cams), self._source_entity_ids,
            )
            if not self._fusions:
                _LOGGER.warning(
                    "CameraPersonDetectedSensor(%s): configured cameras %s resolved "
                    "to zero fusion sources (covered_by_config but None)",
                    self.coordinator.entry.title, room_cams,
                )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "CameraPersonDetectedSensor(%s): fusion resolve failed: %s",
                self.coordinator.entry.title, exc,
            )
            return None
        return self._fusions

    async def async_added_to_hass(self) -> None:
        """Wire event-driven refresh — A-H1/B-HIGH-1/E-MED-2 fix.

        On added: resolve fusion, subscribe to source entity state-change
        events, and subscribe to the room-entry lifecycle signal for cache
        invalidation on options-update / reload (A-M1/E-MED-1).
        """
        await super().async_added_to_hass()
        from homeassistant.helpers.event import (  # noqa: PLC0415
            async_track_state_change_event,
        )
        from homeassistant.helpers.dispatcher import (  # noqa: PLC0415
            async_dispatcher_connect,
        )
        from .domain_coordinators.signals import (  # noqa: PLC0415
            SIGNAL_ROOM_ENTRY_LIFECYCLE,
        )
        from homeassistant.core import callback  # noqa: PLC0415

        def _subscribe_sources():
            # Clean previous state subscription (if any) then re-subscribe.
            if self._unsub_state is not None:
                try:
                    self._unsub_state()
                except Exception:  # noqa: BLE001
                    pass
                self._unsub_state = None
            self._get_fusion()
            # D'-MED-1: also watch F2-collapse losers so a loser's recovery
            # (winner picked while both hosts were down) triggers re-resolve.
            _dropped = [
                d for f in (self._fusions or [])
                for d in getattr(f, "dropped_person_sensors", [])
            ]
            eids = list(self._source_entity_ids) + _dropped
            if not eids:
                return

            _dropped_set = set(_dropped)

            @callback
            def _on_state_change(event):
                # D'-MED-1: a collapse-loser transitioning out of
                # unavailable/unknown means the deterministic winner pick may
                # be stale — re-resolve so a recovered host can win.
                try:
                    eid = event.data.get("entity_id", "")
                    new_st = event.data.get("new_state")
                    if (eid in _dropped_set and new_st is not None
                            and new_st.state not in ("unavailable", "unknown")):
                        self._fusions = None
                        self._source_entity_ids = []
                        _subscribe_sources()
                except Exception:  # noqa: BLE001 — never break state writes
                    pass
                self.async_write_ha_state()

            self._unsub_state = async_track_state_change_event(
                self.hass, eids, _on_state_change,
            )

        _subscribe_sources()

        @callback
        def _on_lifecycle(entry_id, room_name, event):
            # Re-resolve + re-subscribe on THIS room entry's update/reload.
            if entry_id != self.coordinator.entry.entry_id:
                return
            _LOGGER.info(
                "CameraPersonDetectedSensor(%s): lifecycle=%s — re-resolving fusion",
                self.coordinator.entry.title, event,
            )
            self._fusions = None
            self._source_entity_ids = []
            _subscribe_sources()
            self.async_write_ha_state()

        self._unsub_lifecycle = async_dispatcher_connect(
            self.hass, SIGNAL_ROOM_ENTRY_LIFECYCLE, _on_lifecycle,
        )
        self.async_on_remove(self._unsub_lifecycle)

        @callback
        def _cleanup_state():
            if self._unsub_state is not None:
                try:
                    self._unsub_state()
                except Exception:  # noqa: BLE001
                    pass
                self._unsub_state = None
        self.async_on_remove(_cleanup_state)

    def _all_sources(self):
        """Fix #7: flatten sources across all resolved physical cameras."""
        fusions = self._get_fusion() or []
        return [s for f in fusions for s in f.sources]

    @property
    def is_on(self) -> bool:
        """Return True if ANY resolved source binary_sensor across ALL fused
        physical cameras is on (Fix #7: OR across the list)."""
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        if config.get(CONF_DISABLE_CAMERA_PRESENCE):
            return False
        for src in self._all_sources():
            eid = src.person_binary_sensor
            if not eid:
                continue
            try:
                state = self.hass.states.get(eid)
            except Exception:  # noqa: BLE001
                continue
            if state is not None and state.state == "on":
                return True
        return False

    @property
    def extra_state_attributes(self) -> dict:
        """Attribution + agreement/confidence + disabled_by_config."""
        config = {**self.coordinator.entry.data, **self.coordinator.entry.options}
        disabled = bool(config.get(CONF_DISABLE_CAMERA_PRESENCE))
        fusions = self._get_fusion()
        if not fusions:
            return {
                "sources": [],
                "agreement": "no_sources",
                "confidence": "none",
                "resolved_camera_devices": [],
                "disabled_by_config": disabled,
                "configured_cameras": config.get(CONF_ROOM_CAMERAS, []) or [],
            }
        sources_out: list[dict] = []
        on_count = 0
        avail_count = 0
        on_integrations: set[str] = set()
        for src in self._all_sources():
            eid = src.person_binary_sensor
            state = self.hass.states.get(eid) if eid else None
            state_val = state.state if state is not None else "unknown"
            if state_val in ("on", "off"):
                avail_count += 1
                if state_val == "on":
                    on_count += 1
                    if src.integration:
                        on_integrations.add(src.integration)
            sources_out.append({
                "integration": src.integration,
                "entity_id": eid,
                "state": state_val,
                "correlation_basis": src.correlation_basis,
                "face_capability": src.face_capability,
                "physical_camera_id": next(
                    (f.physical_camera_id for f in fusions if src in f.sources), ""
                ),
            })
        # Agreement classification.
        if not sources_out:
            agreement = "no_sources"
        elif len(sources_out) == 1:
            agreement = "single_source"
        elif on_count == avail_count and on_count > 0:
            agreement = "unanimous_on"
        elif on_count == 0:
            agreement = "unanimous_off"
        else:
            agreement = "split"
        # Confidence classification.
        if avail_count == 0:
            confidence = "low" if sources_out else "none"
        elif on_count >= 2:
            confidence = "high"
        elif agreement == "split" or on_count == 1:
            confidence = "medium"
        else:
            confidence = "high"  # unanimous_off with >=2 available
        # Fix #9 (D-MED-3/E-HIGH-2): doctrine deferral — family-independence
        # minimal rule. If ALL ON sources share the same integration, the
        # corroborators aren't truly independent; downgrade high→medium.
        # TODO(plan amendment §corroboration doctrine): implement half-weight
        # per-family, ~3 heterogeneous families cap, capability-diversity
        # preference. Evidence trigger to graduate: multi-family live data
        # showing per-family false-positive rates + a golden-master diff.
        if confidence == "high" and len(on_integrations) <= 1:
            confidence = "medium"
        return {
            "sources": sources_out,
            "agreement": agreement,
            "confidence": confidence,
            "resolved_camera_devices": [s.device_id for s in self._all_sources()],
            "disabled_by_config": disabled,
            "configured_cameras": config.get(CONF_ROOM_CAMERAS, []) or [],
            "resolved_physical_cameras": len(fusions),
        }


class URAUnexpectedPersonSensor(BinarySensorEntity):
    """Integration-level: True when cameras see more persons than BLE can account for.

    v3.5.1 upgrade: uses house-level PersonCensus camera total vs person_coordinator
    active BLE count.  camera_total > ble_active_total → is_on = True.

    Gracefully returns False if either data source is unavailable.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:account-alert"
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{DOMAIN}_census_unexpected_person_detected"
        self._attr_name = "Unexpected Person Detected"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "integration")},
            name="Universal Room Automation",
            manufacturer="Universal Room Automation",
            model="Whole House",
            sw_version=VERSION,
        )
        self._camera_total: int = 0
        self._ble_total: int = 0

    @property
    def is_on(self) -> bool:
        """Return True when cameras see more persons than BLE can identify."""
        census = self.hass.data.get(DOMAIN, {}).get("census")
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")

        if not census or not person_coordinator:
            return False

        result = census.last_result
        self._camera_total = result.house.total_persons if result else 0

        # Count active BLE persons (known, currently tracked as home)
        ble_active: list[str] = []
        if person_coordinator.data:
            ble_active = [
                pid for pid, info in person_coordinator.data.items()
                if info.get("tracking_status") == "active"
            ]
        self._ble_total = len(ble_active)

        return self._camera_total > self._ble_total

    @property
    def extra_state_attributes(self) -> dict:
        """Return camera total, ble total, and derived guest count."""
        # Trigger a fresh read so attributes are always in sync with is_on
        census = self.hass.data.get(DOMAIN, {}).get("census")
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")

        camera_total = 0
        ble_total = 0

        if census and census.last_result:
            camera_total = census.last_result.house.total_persons

        if person_coordinator and person_coordinator.data:
            ble_total = len([
                pid for pid, info in person_coordinator.data.items()
                if info.get("tracking_status") == "active"
            ])

        return {
            "camera_total": camera_total,
            "ble_total": ble_total,
            "guest_count": max(0, camera_total - ble_total),
        }


# ============================================================================
# v3.5.2: CENSUS MISMATCH SENSOR
# ============================================================================


class CensusMismatchSensor(BinarySensorEntity):
    """On when camera count and BLE count diverge for an extended period.

    Enabled by default. Useful for automations that respond to unknown persons.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True

    MISMATCH_THRESHOLD = 2
    MISMATCH_DURATION_MINUTES = 10

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{DOMAIN}_census_mismatch"
        self._attr_name = "Census Mismatch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "integration")},
            name="Universal Room Automation",
            manufacturer="Universal Room Automation",
            model="Whole House",
            sw_version=VERSION,
        )
        self._mismatch_since = None
        self._camera_count: int = 0
        self._ble_count: int = 0

    @property
    def is_on(self) -> bool | None:
        """Return True when camera count and BLE count diverge for 10+ minutes."""
        census_state = self.hass.states.get(
            "sensor.universal_room_automation_persons_in_house"
        )
        confidence_state = self.hass.states.get(
            "sensor.universal_room_automation_census_confidence"
        )

        if not census_state or not confidence_state:
            return None
        if confidence_state.state == "none":
            return False

        try:
            self._camera_count = int(float(census_state.state))
        except (ValueError, TypeError):
            return None

        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if not person_coordinator:
            return None

        self._ble_count = sum(
            1 for p in person_coordinator.data.values()
            if p.get("location") not in (None, "unknown", "away")
        )

        difference = abs(self._camera_count - self._ble_count)
        now = dt_util.now()

        if difference >= self.MISMATCH_THRESHOLD:
            if self._mismatch_since is None:
                self._mismatch_since = now
            elapsed = (now - self._mismatch_since).total_seconds() / 60
            return elapsed >= self.MISMATCH_DURATION_MINUTES
        else:
            self._mismatch_since = None
            return False

    @property
    def extra_state_attributes(self) -> dict:
        """Return mismatch details."""
        return {
            "camera_count": self._camera_count,
            "ble_count": self._ble_count,
            "mismatch_since": self._mismatch_since.isoformat() if self._mismatch_since else None,
            "threshold": self.MISMATCH_THRESHOLD,
            "duration_minutes": self.MISMATCH_DURATION_MINUTES,
        }


# ============================================================================
# v3.5.2: PHONE LEFT BEHIND SENSOR (per person, diagnostic)
# ============================================================================


class PersonPhoneLeftBehindSensor(BinarySensorEntity):
    """Diagnostic: BLE says person is home but camera hasn't seen them recently.

    Fires when:
      - BLE places person in a room (not away/unknown)
      - No camera has seen this person in PHONE_LEFT_BEHIND_HOURS (1h)
      - Camera census is NOT currently seeing unidentified persons
        (if census sees people, the phone holder is likely present)
      - Outside sleep hours (10 PM – 7 AM)

    Disabled by default — enable manually if the signal is reliable in your home.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_has_entity_name = True

    PHONE_LEFT_BEHIND_HOURS: float = 1.0
    SLEEP_START_HOUR: int = 22
    SLEEP_END_HOUR: int = 7

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, person_id: str) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self._person_id = person_id
        self._attr_unique_id = f"{DOMAIN}_person_{person_id.lower().replace(' ', '_')}_phone_left_behind"
        self._attr_name = f"{person_id} Phone Left Behind"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "integration")},
            name="Universal Room Automation",
            manufacturer="Universal Room Automation",
            model="Whole House",
            sw_version=VERSION,
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if phone-left-behind conditions are met."""
        # 1. Check sleep hours — suppress during sleep
        now = dt_util.now()
        hour = now.hour
        if hour >= self.SLEEP_START_HOUR or hour < self.SLEEP_END_HOUR:
            return False

        # 2. Check BLE location
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if not person_coordinator:
            return None
        person_data = person_coordinator.data.get(self._person_id, {})
        ble_location = person_data.get("location")
        if not ble_location or ble_location in ("unknown", "away"):
            return False

        # 3. If camera census currently sees people, suppress —
        #    the phone holder is likely present (census is evidence of presence)
        census = self.hass.data.get(DOMAIN, {}).get("census")
        if census and census.last_result:
            house = census.last_result.house
            if house.total_persons > 0:
                return False

        # 4. Check camera sighting age — 1 hour threshold
        transit_validator = self.hass.data.get(DOMAIN, {}).get("transit_validator")
        if not transit_validator:
            return None
        sighting = transit_validator.get_last_camera_sighting(
            self._person_id,
            max_age_hours=self.PHONE_LEFT_BEHIND_HOURS,
        )
        return sighting is None

    @property
    def extra_state_attributes(self) -> dict:
        """Return diagnostic details."""
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        transit_validator = self.hass.data.get(DOMAIN, {}).get("transit_validator")

        ble_location = None
        hours_since_sighting = None
        census_persons = None

        if person_coordinator:
            person_data = person_coordinator.data.get(self._person_id, {})
            ble_location = person_data.get("location")

        if transit_validator:
            sighting = transit_validator.get_last_camera_sighting(
                self._person_id, max_age_hours=24.0
            )
            if sighting:
                ts = sighting.get("timestamp")
                if ts:
                    if isinstance(ts, str):
                        from homeassistant.util import dt as dt_util2
                        ts = dt_util2.parse_datetime(ts)
                    if ts:
                        delta = dt_util.now() - ts
                        hours_since_sighting = round(delta.total_seconds() / 3600, 2)

        census = self.hass.data.get(DOMAIN, {}).get("census")
        if census and census.last_result:
            census_persons = census.last_result.house.total_persons

        return {
            "person_id": self._person_id,
            "ble_location": ble_location,
            "hours_since_camera_sighting": hours_since_sighting,
            "phone_left_behind_hours": self.PHONE_LEFT_BEHIND_HOURS,
            "census_persons_in_house": census_persons,
        }


# ============================================================================
# v3.6.0-c1: Presence Coordinator Binary Sensors
# ============================================================================


class HouseOccupiedBinarySensor(BinarySensorEntity):
    """True when any person is detected in the house.

    Entity: binary_sensor.ura_house_occupied
    Device: URA: Presence Coordinator
    """

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_has_entity_name = True
    _attr_icon = "mdi:home-account"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import DOMAIN, VERSION
        self._attr_unique_id = f"{DOMAIN}_house_occupied"
        self._attr_name = "House Occupied"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if house is occupied."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        from .domain_coordinators.house_state import HouseState
        return manager.house_state not in (
            HouseState.AWAY, HouseState.VACATION
        )


class HouseSleepingBinarySensor(BinarySensorEntity):
    """True when house is in SLEEP state.

    Entity: binary_sensor.ura_house_sleeping
    Device: URA: Presence Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:sleep"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import DOMAIN, VERSION
        self._attr_unique_id = f"{DOMAIN}_house_sleeping"
        self._attr_name = "House Sleeping"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if house is sleeping."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        from .domain_coordinators.house_state import HouseState
        return manager.house_state == HouseState.SLEEP


class GuestModeBinarySensor(BinarySensorEntity):
    """True when house is in GUEST mode.

    Entity: binary_sensor.ura_guest_mode
    Device: URA: Presence Coordinator
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-group"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import DOMAIN, VERSION
        self._attr_unique_id = f"{DOMAIN}_guest_mode"
        self._attr_name = "Guest Mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "presence_coordinator")},
            name="URA: Presence Coordinator",
            manufacturer="Universal Room Automation",
            model="Presence Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if in guest mode."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        from .domain_coordinators.house_state import HouseState
        return manager.house_state == HouseState.GUEST


# ============================================================================
# v3.6.0-c2: Safety Coordinator Binary Sensors
# ============================================================================


class SafetyAlertBinarySensor(BinarySensorEntity):
    """True when any safety hazard is active.

    Entity: binary_sensor.ura_safety_alert
    Device: URA: Safety Coordinator
    """

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import DOMAIN, VERSION
        self._attr_unique_id = f"{DOMAIN}_safety_coordinator_safety_alert"
        self._attr_name = "Safety Alert"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "safety_coordinator")},
            name="URA: Safety Coordinator",
            manufacturer="Universal Room Automation",
            model="Safety Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if any safety hazard is active."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        safety = manager.coordinators.get("safety")
        if safety is None:
            return False
        return len(safety.active_hazards) > 0

    @property
    def extra_state_attributes(self) -> dict:
        """Return hazard details."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {"hazard_type": None, "location": None, "severity": None}
        safety = manager.coordinators.get("safety")
        if safety is None or not safety.active_hazards:
            return {"hazard_type": None, "location": None, "severity": None}

        # Return the worst active hazard
        worst = max(
            safety.active_hazards.values(),
            key=lambda h: h.severity,
        )
        attrs = {
            "hazard_type": worst.type.value,
            "location": worst.location,
            "severity": worst.severity.name.lower(),
            "active_count": len(safety.active_hazards),
        }
        # v3.6.0.3: All active hazards, not just worst
        attrs["all_hazards"] = [
            {"hazard_type": h.type.value, "location": h.location,
             "severity": h.severity.name.lower()}
            for h in safety.active_hazards.values()
        ]
        return attrs

    async def async_added_to_hass(self) -> None:
        """Subscribe to safety entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle safety entity update signal."""
        self.async_schedule_update_ha_state()


class SafetyWaterLeakBinarySensor(AggregationEntity, BinarySensorEntity):
    """Water leak/flooding indicator.

    v3.6.0.3: Glanceable binary sensor — any water problem?
    Entity: binary_sensor.ura_safety_water_leak
    """

    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_has_entity_name = True
    _attr_icon = "mdi:water-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_water_leak"
        self._attr_name = "Safety Water Leak"
        from homeassistant.helpers.device_registry import DeviceInfo
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "safety_coordinator")},
        )

    @property
    def is_on(self) -> bool:
        """Return True if any water leak or flooding hazard active."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        safety = manager.coordinators.get("safety")
        if safety is None:
            return False
        status = safety.get_water_leak_status()
        return status.get("active", False)

    @property
    def extra_state_attributes(self) -> dict:
        """Return water leak details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        safety = manager.coordinators.get("safety")
        if safety is None:
            return {}
        status = safety.get_water_leak_status()
        if not status.get("active"):
            return {}
        return {
            "locations": status.get("locations", []),
            "sensor_ids": status.get("sensor_ids", []),
            "sensor_count": status.get("sensor_count", 0),
            "flooding_escalated": status.get("flooding_escalated", False),
            "first_detected": status.get("first_detected"),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to safety entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle safety entity update signal."""
        self.async_schedule_update_ha_state()


class SafetyAirQualityBinarySensor(AggregationEntity, BinarySensorEntity):
    """Air quality problem indicator.

    v3.6.0.3: Glanceable binary sensor — any air quality problem?
    Entity: binary_sensor.ura_safety_air_quality
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True
    _attr_icon = "mdi:air-filter"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_safety_air_quality"
        self._attr_name = "Safety Air Quality"
        from homeassistant.helpers.device_registry import DeviceInfo
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "safety_coordinator")},
        )

    @property
    def is_on(self) -> bool:
        """Return True if any air quality hazard active."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        safety = manager.coordinators.get("safety")
        if safety is None:
            return False
        status = safety.get_air_quality_status()
        return status.get("active", False)

    @property
    def extra_state_attributes(self) -> dict:
        """Return air quality hazard details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        safety = manager.coordinators.get("safety")
        if safety is None:
            return {}
        status = safety.get_air_quality_status()
        if not status.get("active"):
            return {}
        return {
            "hazard_types": status.get("hazard_types", []),
            "locations": status.get("locations", []),
            "sensor_ids": status.get("sensor_ids", []),
            "worst_severity": status.get("worst_severity"),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to safety entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SAFETY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SAFETY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle safety entity update signal."""
        self.async_schedule_update_ha_state()


# ============================================================================
# v3.6.0-c3: Security Coordinator binary sensors
# ============================================================================


class SecurityAlertBinarySensor(BinarySensorEntity):
    """True when a security alert is active.

    Entity: binary_sensor.ura_security_alert
    Device: URA: Security Coordinator
    """

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import DOMAIN, VERSION
        self._attr_unique_id = f"{DOMAIN}_security_coordinator_security_alert"
        self._attr_name = "Security Alert"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "security_coordinator")},
            name="URA: Security Coordinator",
            manufacturer="Universal Room Automation",
            model="Security Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if a security alert is active."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return False
        security = manager.coordinators.get("security")
        if security is None:
            return False
        return security.active_alert

    @property
    def extra_state_attributes(self) -> dict:
        """Return alert details."""
        from .const import DOMAIN
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {"alert_type": None, "armed_state": None}
        security = manager.coordinators.get("security")
        if security is None or not security.active_alert:
            return {"alert_type": None, "armed_state": None}
        details = security.alert_details
        return {
            "alert_type": details.get("type"),
            "armed_state": security.armed_state.value,
            "entity_id": details.get("entity_id"),
            "timestamp": details.get("timestamp"),
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to security entity updates."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_SECURITY_ENTITIES_UPDATE
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SECURITY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle security entity update signal."""
        self.async_schedule_update_ha_state()


# ============================================================================
# v3.6.29: Notification Manager Binary Sensor
# ============================================================================


class NMActiveAlertBinarySensor(BinarySensorEntity):
    """True when an unacknowledged CRITICAL/HIGH alert exists.

    Entity: binary_sensor.ura_notification_active_alert
    Device: URA: Notification Manager
    """

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import DOMAIN, VERSION
        self._attr_unique_id = f"{DOMAIN}_notification_active_alert"
        self._attr_name = "Notification Active Alert"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "notification_manager")},
            name="URA: Notification Manager",
            manufacturer="Universal Room Automation",
            model="Notification Manager",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool:
        """Return True if an active alert exists."""
        from .const import DOMAIN
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return False
        return nm.active_alert

    @property
    def extra_state_attributes(self) -> dict:
        """Return alert state details."""
        from .const import DOMAIN
        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is None:
            return {"alert_state": "not_initialized"}
        return {"alert_state": nm.alert_state}

    async def async_added_to_hass(self) -> None:
        """Subscribe to NM alert state changes."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_NM_ALERT_STATE_CHANGED
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_NM_ALERT_STATE_CHANGED, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Handle NM alert state change signal."""
        self.async_schedule_update_ha_state()


# ============================================================================
# v3.7.3: Energy Coordinator binary sensors
# ============================================================================


class EnergyEnvoyAvailableBinarySensor(AggregationEntity, BinarySensorEntity):
    """True when the Envoy is responding (SOC + storage mode readable).

    When off, the Energy Coordinator holds current state and issues no commands.
    Entity: binary_sensor.ura_energy_coordinator_envoy_available
    Device: URA: Energy Coordinator
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_icon = "mdi:solar-panel"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_envoy_available"
        self._attr_name = "Energy Envoy Available"
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if Envoy is available."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.battery_strategy.envoy_available

    @property
    def extra_state_attributes(self) -> dict:
        """Return Envoy availability details."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return {}
        energy = manager.coordinators.get("energy")
        if energy is None:
            return {}
        summary = energy.get_energy_summary()
        return {
            "unavailable_count": summary.get("envoy_unavailable_count", 0),
            "last_available": summary.get("envoy_last_available"),
        }


class EnergyL1ChargerBinarySensor(AggregationEntity, BinarySensorEntity):
    """L1 charger status — on when any Moes plug socket is on.

    Entity: binary_sensor.ura_energy_l1_charger_garage_a
    Device: URA: Energy Coordinator
    """

    _attr_device_class = BinarySensorDeviceClass.PLUG
    _attr_has_entity_name = True
    _attr_icon = "mdi:ev-plug-type1"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_l1_charger_garage_a"
        self._attr_name = "L1 Charger Garage A"
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if any L1 charger socket is on (charging)."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        energy = manager.coordinators.get("energy")
        if energy is None:
            return None
        return energy.l1_charger_active


# ============================================================================
# v4.7.x Cycle A: Weather Provider Divergence
# ============================================================================


class WeatherDivergenceBinarySensor(AggregationEntity, BinarySensorEntity):
    """On when ≥2 weather providers disagree beyond the configured threshold.

    Entity: binary_sensor.ura_weather_divergence
    Device: URA: Energy Coordinator
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_icon = "mdi:weather-cloudy-alert"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_weather_divergence"
        self._attr_name = "Weather Divergence"
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to SIGNAL_WEATHER_DIVERGENCE_DETECTED for reactive updates (WPM-H1)."""
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import SIGNAL_WEATHER_DIVERGENCE_DETECTED
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_WEATHER_DIVERGENCE_DETECTED, self._on_divergence_signal,
            )
        )

    @callback
    def _on_divergence_signal(self, _payload=None) -> None:
        """Handle divergence signal — push updated state to HA."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return False when WeatherProviderManager is not set up (WPM-H5)."""
        return self.hass.data.get(DOMAIN, {}).get("weather_manager") is not None

    @property
    def is_on(self) -> bool | None:
        """Return True when provider divergence exceeds configured threshold."""
        try:
            mgr = self.hass.data.get(DOMAIN, {}).get("weather_manager")
            if mgr is None:
                return False
            return mgr.is_divergent
        except Exception:
            return False

    @property
    def extra_state_attributes(self) -> dict:
        """Return divergence details including configured threshold (WPM-H6)."""
        try:
            mgr = self.hass.data.get(DOMAIN, {}).get("weather_manager")
            if mgr is None:
                return {}
            return {
                "divergence_f": mgr.divergence_f,
                "threshold_f": mgr.divergence_threshold_f,
                "provider_high_map": dict(mgr._provider_highs),
            }
        except Exception:
            return {}


# ============================================================================
# v4.0.0-B2: Bayesian Occupancy Anomaly
# ============================================================================


class OccupancyAnomalyBinarySensor(UniversalRoomEntity, BinarySensorEntity):
    """Per-room binary sensor: true when occupancy is anomalous.

    Anomalous = room is occupied but Bayesian predicted < 10% probability
    AND learning status is ACTIVE (enough observations to be confident).

    Suppressed during GUEST house state to avoid false positives from
    untracked visitors.

    Fires SIGNAL_OCCUPANCY_ANOMALY and NM alert on activation.
    Diagnostic, disabled by default.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:account-alert"

    def __init__(self, coordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "occupancy_anomaly", "Occupancy Anomaly")
        self._anomaly_data: dict = {}
        self._is_anomaly: bool = False
        self._last_alert_time = None
        self._startup_time = dt_util.utcnow()

    @property
    def is_on(self) -> bool:
        """Return true if occupancy is anomalous."""
        return self._is_anomaly

    @property
    def extra_state_attributes(self) -> dict:
        """Return anomaly score details."""
        attrs = dict(self._anomaly_data) if self._anomaly_data else {}
        attrs["room"] = self.coordinator.entry.data.get("room_name", "")
        return attrs

    async def async_update(self) -> None:
        """Evaluate anomaly score."""
        predictor = self.hass.data.get(DOMAIN, {}).get("bayesian_predictor")
        if predictor is None:
            self._is_anomaly = False
            self._anomaly_data = {}
            return

        room_name = self.coordinator.entry.data.get("room_name", "")
        is_occupied = bool(
            self.coordinator.data.get(STATE_OCCUPIED) if self.coordinator.data else False
        )

        self._anomaly_data = predictor.get_anomaly_score(room_name, is_occupied)
        was_anomaly = self._is_anomaly
        new_anomaly = self._anomaly_data.get("anomaly", False)

        # Suppress during GUEST house state
        if new_anomaly:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            if manager is not None:
                house_state = str(getattr(manager, "house_state", None) or "").lower()
                if house_state == "guest":
                    new_anomaly = False
                    self._anomaly_data["suppressed_reason"] = "guest_mode"

        self._is_anomaly = new_anomaly

        # Fire signal and NM alert on new anomaly (rising edge)
        # Skip alerts in observation mode (Bug Class #23)
        if new_anomaly and not was_anomaly:
            if not getattr(self.coordinator, '_observation_mode', False):
                await self._fire_anomaly_alert(room_name)

    async def _fire_anomaly_alert(self, room_name: str) -> None:
        """Fire SIGNAL_OCCUPANCY_ANOMALY and send NM notification."""
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        from .domain_coordinators.signals import SIGNAL_OCCUPANCY_ANOMALY

        now = dt_util.now()
        # Startup grace period: suppress alerts for 5 minutes after init
        if (dt_util.utcnow() - self._startup_time).total_seconds() < 300:
            return
        # Cooldown: don't re-alert within 30 minutes
        if self._last_alert_time is not None:
            elapsed = (now - self._last_alert_time).total_seconds()
            if elapsed < 1800:
                return

        self._last_alert_time = now

        async_dispatcher_send(
            self.hass,
            SIGNAL_OCCUPANCY_ANOMALY,
            {
                "room": room_name,
                "predicted_probability": self._anomaly_data.get("predicted_probability"),
                "time_bin": self._anomaly_data.get("time_bin"),
                "day_type": self._anomaly_data.get("day_type"),
            },
        )

        # v4.6.1 canary: persist to unified anomaly_log via AnomalyEvent.
        # Parallel write — existing signal dispatch and NM alert unchanged.
        await self._store_bayesian_anomaly_event(room_name)

        # NM alert — severity based on time of day
        is_night = now.hour < 6 or now.hour >= 22
        severity = "high" if is_night else "medium"

        nm = self.hass.data.get(DOMAIN, {}).get("notification_manager")
        if nm is not None:
            try:
                await nm.async_notify(
                    title=f"Unexpected occupancy: {room_name}",
                    message=(
                        f"Room '{room_name}' is occupied but Bayesian model predicted "
                        f"<10% probability for this time period."
                    ),
                    severity=severity,
                    source="bayesian_predictor",
                )
            except Exception as e:
                _LOGGER.debug("NM alert for occupancy anomaly failed: %s", e)

    async def _store_bayesian_anomaly_event(self, room_name: str) -> None:
        """Persist bayesian occupancy anomaly to unified anomaly_log.

        v4.6.1 canary migration: proves AnomalyEvent shape for an existing
        frequent emitter. Existing NM + signal paths remain unchanged.
        """
        from .domain_coordinators.anomaly_event import (
            AnomalyEvent,
            AnomalySeverity,
            AnomalyType,
        )

        db = self.hass.data.get(DOMAIN, {}).get("database")
        if db is None:
            return

        event = AnomalyEvent(
            coordinator="bayesian",
            type="bayesian.prediction_anomaly",
            severity=AnomalySeverity.WARNING,
            anomaly_type=AnomalyType.POINT_IN_TIME,
            detected_at=dt_util.utcnow().isoformat(),
            payload={
                "room_id": room_name,
                "predicted_probability": self._anomaly_data.get("predicted_probability"),
                "time_bin": self._anomaly_data.get("time_bin"),
                "day_type": self._anomaly_data.get("day_type"),
                "learning_status": self._anomaly_data.get("learning_status"),
            },
            room_id=room_name,
        )
        await db.save_anomaly_event(event)


# ============================================================================
# v4.7.x D2: EC Sub-Switch Sync Health Sensor
# ============================================================================


class ECSubSwitchesSyncedSensor(AggregationEntity, BinarySensorEntity):
    """Reports whether the 5 EC sub-switches have completed their saved-state restore.

    Entity: binary_sensor.ura_energy_coordinator_sub_switches_synced
    Device: URA: Energy Coordinator

    True  — Energy Coordinator is registered and all 5 sub-switches have had
            the opportunity to restore their saved values via
            SIGNAL_ENERGY_COORDINATOR_READY.
    False — EC coordinator is not yet registered (startup race in progress)
            or at least one switch still has a pending deferred restore.

    When False persists for >10 min, the URA sub-switch restore is likely
    stuck and should be investigated (check HA logs for "deferred restore"
    warnings for the affected switch).

    Bug Class #5 (startup race), #10 (cross-restart state loss), #38 (unsub).
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:toggle-switch-variant"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    # Sub-switch unique-id suffixes (used to look up switch entities)
    _SUB_SWITCH_SUFFIXES = (
        "grid_import_cap",
        "load_shedding",
        "excess_solar",
        "arbitrage",
        "ev_tou_management",
    )

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_energy_coordinator_sub_switches_synced"
        self._attr_name = "EC Sub-Switches Synced"
        from homeassistant.helpers.device_registry import DeviceInfo
        from .const import VERSION
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_coordinator")},
            name="URA: Energy Coordinator",
            manufacturer="Universal Room Automation",
            model="Energy Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )
        # Track when EC first became ready (for >10 min mismatch detection)
        self._ec_ready_at: dt_util.dt.datetime | None = None

    def _get_energy(self):
        """Return EnergyCoordinator or None."""
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        return manager.coordinators.get("energy") if manager else None

    async def async_added_to_hass(self) -> None:
        """Subscribe to EC-ready and energy-update signals.

        Bug Class #38: unsub tracked via async_on_remove.
        """
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.signals import (
            SIGNAL_ENERGY_COORDINATOR_READY,
            SIGNAL_ENERGY_ENTITIES_UPDATE,
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ENERGY_COORDINATOR_READY, self._handle_ec_ready
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_ENERGY_ENTITIES_UPDATE, self._handle_update
            )
        )

    @callback
    def _handle_ec_ready(self) -> None:
        """Record EC-ready timestamp and refresh state."""
        if self._ec_ready_at is None:
            self._ec_ready_at = dt_util.utcnow()
            _LOGGER.info(
                "ECSubSwitchesSyncedSensor: EC coordinator ready at %s",
                self._ec_ready_at.isoformat(),
            )
        self.async_schedule_update_ha_state()

    @callback
    def _handle_update(self) -> None:
        """Refresh state on each energy decision cycle."""
        self.async_schedule_update_ha_state()

    @property
    def is_on(self) -> bool | None:
        """Return True (problem) when any sub-switch has not completed restore.

        NOTE: BinarySensorDeviceClass.PROBLEM convention: True = problem exists.
        We return True (problem) when EC is not yet registered OR when one or
        more sub-switches still have a pending deferred restore.

        v4.7.x H1 fix-up: uses energy.sub_switches_synced() which reads the
        per-switch completion counter (notify_sub_switch_restore_complete).
        EC registered alone is a weaker guarantee — a switch could be stuck at
        its constructor-seed value even after EC registers.
        """
        energy = self._get_energy()
        if energy is None:
            # EC not yet registered — sub-switches using seed values
            return True  # problem: not synced
        # EC registered: check whether all sub-switches completed deferred restore
        try:
            if not energy.sub_switches_synced():
                return True  # problem: at least one switch still pending
        except Exception:
            # sub_switches_synced() not available on older EC instances
            pass
        return False  # no problem: EC registered and all switches synced

    @property
    def extra_state_attributes(self) -> dict:
        """Return sync details for diagnostics."""
        energy = self._get_energy()
        attrs: dict = {
            "ec_registered": energy is not None,
            "ec_ready_at": (
                self._ec_ready_at.isoformat() if self._ec_ready_at else None
            ),
        }
        if energy is not None:
            try:
                attrs["pending_sub_switch_restores"] = energy._pending_sub_switch_restores
                attrs["all_switches_synced"] = energy.sub_switches_synced()
            except Exception:
                pass
        if energy is not None and self._ec_ready_at is not None:
            age_s = (dt_util.utcnow() - self._ec_ready_at).total_seconds()
            attrs["seconds_since_ec_ready"] = round(age_s, 1)
            attrs["mismatch_alert"] = age_s > 600  # >10 min still checking
        return attrs



# =============================================================================
# v4.7.8 D5 — Egress Window HVAC Pause binary sensors (end-of-file append)
# -----------------------------------------------------------------------------
# Per-room and per-canonical-HVAC-zone egress window-open sensors. Read from
# in-memory EgressManager + room coordinator state. No DB I/O on update
# (Bug Class #26).
# =============================================================================


class RoomEgressWindowOpenSensor(UniversalRoomEntity, BinarySensorEntity):
    """Per-room egress window open indicator (v4.7.8 D5).

    Reads the room's CONF_WINDOW_SENSORS state. ON iff is_egress_window=True
    AND raw window state is "on". Subscribes to raw window_sensor state
    changes for instant flip (no 5-min decision-tick lag).

    v4.7.8 fix-up C-M2: inherits UniversalRoomEntity for consistent
    device-association + name-prefixing; was diverging from the pattern.
    """

    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_icon = "mdi:window-open-variant"
    _attr_translation_key = "egress_window_open"

    def __init__(self, coordinator) -> None:
        # UniversalRoomEntity handles device_info, unique_id, has_entity_name.
        super().__init__(
            coordinator,
            entity_type="egress_window_open",
            name="Egress Window Open",
        )
        # Read entry config lazily so reconfigure picks up new values.
        self._entry = coordinator.entry
        self._unsub_state = None

    def _config_merged(self) -> dict:
        return {**self._entry.data, **self._entry.options}

    @property
    def _window_sensor(self) -> str | None:
        return self._config_merged().get(CONF_WINDOW_SENSORS) or None

    @property
    def _is_egress(self) -> bool:
        # Lazy default per v4.7.4.4 Bug Class #46 doctrine.
        from .const import CONF_IS_EGRESS_WINDOW, DEFAULT_IS_EGRESS_WINDOW
        cfg = self._config_merged()
        return bool(cfg.get(CONF_IS_EGRESS_WINDOW, DEFAULT_IS_EGRESS_WINDOW))

    @property
    def is_on(self) -> bool:
        if not self._is_egress:
            return False
        ws = self._window_sensor
        if not ws:
            return False
        try:
            st = self.coordinator.hass.states.get(ws)
            return st is not None and st.state == "on"
        except Exception:
            return False

    @property
    def available(self) -> bool:
        return self._window_sensor is not None

    @property
    def extra_state_attributes(self) -> dict:
        ws = self._window_sensor
        raw = None
        if ws:
            try:
                st = self.coordinator.hass.states.get(ws)
                raw = st.state if st is not None else None
            except Exception:
                raw = None
        return {
            "is_egress": self._is_egress,
            "raw_window_state": raw,
            "room_name": self._entry.data.get("room_name", ""),
            "window_sensor": ws,
        }

    # v4.7.8 fix-up C-M2: device_info is set by UniversalRoomEntity.__init__.

    async def async_added_to_hass(self) -> None:
        """Subscribe to raw window_sensor state changes for instant flip."""
        await super().async_added_to_hass()
        from homeassistant.helpers.event import async_track_state_change_event

        ws = self._window_sensor
        if not ws:
            return

        @callback
        def _on_state_change(_event):
            self.async_write_ha_state()

        self._unsub_state = async_track_state_change_event(
            self.coordinator.hass, [ws], _on_state_change,
        )
        self.async_on_remove(self._unsub_state)


class HVACZoneEgressWindowOpenSensor(BinarySensorEntity):
    """Per-canonical-HVAC-zone egress window open rollup (v4.7.8 D5).

    ON iff EgressManager.zone_aggregate(zone_id) is True (any egress room in
    the zone is open AND counter / pause state engaged).
    """

    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_icon = "mdi:window-open"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        zone_id: str,
        zone_name: str,
    ) -> None:
        from homeassistant.helpers.device_registry import DeviceInfo
        self.hass = hass
        self._entry = entry
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._attr_unique_id = f"{DOMAIN}_hvac_zone_{zone_id}_egress_window_open"
        self._attr_name = f"{zone_name} Egress Window Open"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hvac_coordinator")},
            name="URA: HVAC Coordinator",
            manufacturer="Universal Room Automation",
            model="HVAC Coordinator",
            sw_version=VERSION,
            via_device=(DOMAIN, "coordinator_manager"),
        )

    def _get_egress(self):
        manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        if manager is None:
            return None
        hvac = manager.coordinators.get("hvac")
        if hvac is None:
            return None
        return getattr(hvac, "egress_manager", None)

    @property
    def is_on(self) -> bool:
        em = self._get_egress()
        if em is None:
            return False
        try:
            return bool(em.zone_aggregate(self._zone_id))
        except Exception:
            return False

    @property
    def extra_state_attributes(self) -> dict:
        em = self._get_egress()
        if em is None:
            return {"zone_id": self._zone_id}
        try:
            label = em.state_label(self._zone_id)
        except Exception:
            label = "idle"
        return {
            "zone_id": self._zone_id,
            "state_label": label,
        }

    @property
    def available(self) -> bool:
        return self._get_egress() is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        from .domain_coordinators.hvac_const import SIGNAL_HVAC_ENTITIES_UPDATE

        @callback
        def _on_update(*_a, **_kw):
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_HVAC_ENTITIES_UPDATE, _on_update)
        )


# =============================================================================
# Fan-noise Mode-2 — per-room "recheck in progress" diagnostic
# -----------------------------------------------------------------------------
# Disabled by default. is_on reads the FanRecheckManager state for this room
# each access — armed/paused/restoring map True; idle/cooldown/unknown map
# False. The attrs surface FanRecheckManager.get_room_attrs as-is for
# operator visibility (state + last_outcome + last_attempt_iso + layer).
# =============================================================================


class RoomFanRecheckInProgressSensor(
    UniversalRoomEntity, BinarySensorEntity,
):
    """True while FanRecheckManager is actively rechecking this room."""

    _attr_icon = "mdi:fan-clock"
    _attr_entity_registry_enabled_default = False

    _IN_FLIGHT = frozenset({"armed", "paused", "restoring"})

    def __init__(self, coordinator: UniversalRoomCoordinator) -> None:
        super().__init__(
            coordinator, "fan_recheck_in_progress", "Fan Recheck In Progress",
        )

    def _manager_attrs(self) -> dict:
        try:
            manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
            presence = (
                manager.coordinators.get("presence") if manager else None
            )
            fr_mgr = (
                getattr(presence, "_fan_recheck_manager", None)
                if presence is not None else None
            )
            room_name = self.coordinator.entry.data.get("room_name", "")
            if fr_mgr is None or not room_name:
                return {}
            return fr_mgr.get_room_attrs(room_name) or {}
        except Exception:  # noqa: BLE001
            return {}

    @property
    def is_on(self) -> bool:
        attrs = self._manager_attrs()
        return str(attrs.get("fan_recheck_state", "idle")) in self._IN_FLIGHT

    @property
    def extra_state_attributes(self) -> dict:
        attrs = self._manager_attrs()
        # Idempotent default shape — operator gets the same keys whether
        # or not the manager has seen this room yet.
        return {
            "fan_recheck_state": attrs.get("fan_recheck_state", "idle"),
            "fan_recheck_last_outcome": attrs.get(
                "fan_recheck_last_outcome",
            ),
            "fan_recheck_last_attempt_iso": attrs.get(
                "fan_recheck_last_attempt_iso",
            ),
            "fan_recheck_ble_ladder_layer": attrs.get(
                "fan_recheck_ble_ladder_layer", "none",
            ),
        }

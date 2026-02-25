# PLANNING: v3.5.2 Cycle 6 — Transit Validation & Warehoused Sensors

**Version:** 1.0
**Date:** 2026-02-23
**Parent:** PLANNING_v3_5_0_Camera_Intelligence.md (original vision)
**Status:** Planning
**Depends on:** v3.5.1 Slim (camera-extends-occupancy, zone aggregation via house-level census, unexpected person sensor, perimeter alerting)

> **Note:** v3.5.1 shipped the Slim Cycle 4 plan — no per-room camera-BLE fusion exists. All references to per-room fusion data have been removed from this plan.

---

## OVERVIEW

Cycle 6 is the final camera intelligence cycle before v3.6.0 domain coordinators. It has two focused deliverables:

1. **Transit path validation** — Camera data enriches the existing `TransitionDetector`. Transitions graduate from anonymous motion events to identity-aware validated paths. The `PersonLikelyNextRoomSensor` gets a camera-confidence boost. A phone-left-behind diagnostic sensor is introduced.

2. **Warehoused sensors from Cycle 3** — Six sensors that were explicitly deferred: entry/exit counts, entry/exit timestamps, census mismatch detection, and per-zone unidentified counts.

**What does NOT ship:**
- Security Coordinator logic (v3.6.0)
- Unidentified face storage or labeling UI (future)
- Automated responses to phone-left-behind (too noisy — diagnostic only)
- Any new config flow steps (all needed config keys exist from Cycle 3, plus `CONF_FACE_RECOGNITION_ENABLED` added this cycle)

**Boundary with prior cycles:**
- Cycle 3 (v3.5.0): Camera census foundation — `CameraIntegrationManager`, `PersonCensus`, census sensors
- Cycle 4 (v3.5.1): Camera-extends-occupancy, zone aggregation via house-level census, unexpected person sensor, perimeter alerting
- Cycle 6 (v3.5.2): Transit validation on top of existing `TransitionDetector`, plus warehoused sensors

---

## IMPLEMENTATION

### Section 1: Transit Path Validation

The `TransitionDetector` in `transitions.py` currently detects room-to-room transitions from anonymous `ura_person_location_change` events. It classifies each transition as `direct`, `via_hallway`, or `separate` based on timing, and records a confidence score.

Camera data adds two things:
- **PATH PLAUSIBILITY**: Did a person actually appear on the shared-space cameras (hallways, foyers, stairs)? If BLE says John went office → kitchen but no hallway or staircase camera saw anyone, the transition is less trustworthy.
- **WHO** transited: face recognition at shared-space cameras (foyer fisheye, staircase, upstairs hall, master hallway) can confirm or contradict which person BLE says made the transit. This is tracked as a separate identity validation attribute, not a confidence delta.

#### 1.1 New File: `transit_validator.py`

New module, ~280 lines. Does not replace `TransitionDetector` — it is called by it after a transition is detected to augment confidence.

```python
class TransitValidator:
    """Validates room transitions using camera checkpoint data.

    Called by TransitionDetector after each transition is recorded.
    Camera data is optional — all methods degrade gracefully to
    returning the original BLE-only confidence if no camera data exists.
    """

    # If the egress or shared-space camera last saw this person more than
    # this many seconds ago, we can't use it as a transit checkpoint.
    CHECKPOINT_STALE_SECONDS = 90

    # Time window within which a camera checkpoint must have fired
    # after BLE said the person left room A (to count as "path confirmed").
    CHECKPOINT_WINDOW_SECONDS = 120

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        # Map: person_id -> list of {camera_entity_id, timestamp, room}
        # Populated by listening to camera person detection state changes.
        self._camera_sightings: dict[str, list[dict]] = {}
        self._unsub: list = []

    async def async_init(self) -> None:
        """Subscribe to camera person detection entities.

        Pulls the list of configured camera entities from hass.data[DOMAIN]:
        - interior camera entities (CONF_CAMERA_PERSON_ENTITIES per room)
        - egress cameras (CONF_EGRESS_CAMERAS at integration level)

        For each entity, listens to state changes. When a camera fires,
        records a sighting entry keyed by person_id (if face recognition
        provides an ID) or as "unidentified". Unidentified sightings are
        used for path plausibility but not person confirmation.
        """

    async def validate_transition(
        self,
        transition: RoomTransition,
        concurrent_transitions: list[RoomTransition] | None = None,
    ) -> TransitValidationResult:
        """Assess how well camera data supports a recorded transition.

        Returns a TransitValidationResult with path validation and
        identity validation as separate concerns.

        When concurrent_transitions is provided, uses
        _correlate_sighting_to_transition() to assign shared-space
        camera sightings to the correct person.

        This method is called from TransitionDetector._notify_listeners
        after the transition is logged.
        """

    def get_last_camera_sighting(
        self,
        person_id: str,
        max_age_hours: float = 4.0,
    ) -> dict | None:
        """Return the most recent camera sighting for a person.

        Used by phone-left-behind detection. Returns None if no sighting
        within max_age_hours or if person has never been seen by cameras.
        """

    def _get_shared_space_cameras(self) -> list[str]:
        """Return all shared-space camera entity IDs (hallways, foyers, stairs).

        Instead of computing topology between specific rooms, we check
        ALL shared-space cameras. A sighting on any shared-space camera
        within the checkpoint window is treated as path support.

        This is less precise than room-to-room topology but works without
        adjacency configuration and handles multi-person scenarios cleanly.
        """

    def _correlate_sighting_to_transition(
        self,
        transition: RoomTransition,
        concurrent_transitions: list[RoomTransition],
        sightings: list[dict],
    ) -> str:
        """Assign camera sightings to transitions when multiple people transit simultaneously.

        Rules:
        1. Face-matched sighting → assign to matching person's transition
        2. Unidentified sighting → assign to closest-timed transition
        3. If sightings < transitions, unmatched transitions get "no_camera_data" (not negative)
        4. If sightings >= transitions, all get "path_plausible"
        """

    async def _async_cleanup_sightings(self, now: datetime) -> None:
        """Periodic cleanup — remove sightings older than 4 hours."""
```

**Dataclass:**

```python
@dataclass
class TransitValidationResult:
    # Path validation
    path_validated: bool
    path_confidence_delta: float  # -0.15 to +0.10, applied to transition confidence
    checkpoint_rooms: list[str]
    path_method: str  # "path_confirmed" | "path_plausible" | "no_camera_data" | "path_implausible"

    # Identity validation (separate concern)
    identity_status: str  # "confirmed" | "unidentified" | "mismatch" | "unavailable"
    camera_person_id: str | None  # Face-recognized ID (may differ from BLE ID)
```

**Path validation confidence deltas** (applied to transition confidence):

| Camera Result | Delta |
|---|---|
| Shared-space cameras fired, timing matches | +0.10 |
| Shared-space cameras didn't fire (short window, plausible) | 0.00 |
| Shared-space cameras active but didn't fire during transit | -0.15 |
| No shared-space camera data at all | 0.00 (unchanged) |

**Identity validation** (separate attribute, NOT a confidence delta on transition):

| Camera Result | Attribute Value |
|---|---|
| Face confirmed matches BLE identity | "confirmed" |
| Face detected but not recognized | "unidentified" |
| Camera sees different person than BLE claims | "mismatch" |
| No face recognition data | "unavailable" |

**Multi-person transit handling:**

When two people transit simultaneously, the `_correlate_sighting_to_transition()` method handles attribution:

- **Two people transiting from the same room to different rooms across shared space:** Correlate by `person_id` (face) when available, and by timing window when not. If two BLE transitions happen within 30 seconds and the shared-space camera fired once, attribute the camera sighting to the transition whose timing best matches (closest to camera event timestamp).
- **Two people transiting to the same room:** If BLE says person A and person B both moved to kitchen within 60 seconds, and hallway camera saw 2 people, both transitions get `path_plausible`. If camera saw 1 person, the closer-timed transition gets `path_plausible`, the other gets `no_camera_data` (not negative).

#### 1.2 Modifications to `transitions.py`

**Augment `TransitionDetector` to call `TransitValidator` after recording a transition:**

```python
# In __init__:
self._transit_validator: TransitValidator | None = None

# New method:
def set_transit_validator(self, validator: TransitValidator) -> None:
    """Wire in the TransitValidator after it is initialized."""
    self._transit_validator = validator

# In _on_location_change, after _log_transition():
if self._transit_validator:
    validation = await self._transit_validator.validate_transition(transition)
    if validation.path_confidence_delta != 0.0:
        # Re-log to database with updated confidence
        # (update the row just written, don't insert duplicate)
        await self._update_transition_confidence(
            transition, validation
        )
    # Attach validation result to notification payload
    transition._validation = validation

# New method:
async def _update_transition_confidence(
    self,
    transition: RoomTransition,
    validation: TransitValidationResult,
) -> None:
    """Update the confidence of the most recently logged transition."""
    try:
        await self.database.update_transition_validation(
            person_id=transition.person_id,
            timestamp=transition.timestamp,
            new_confidence=min(1.0, transition.confidence + validation.path_confidence_delta),
            validation_method=validation.path_method,
            checkpoint_rooms=validation.checkpoint_rooms,
        )
    except Exception as e:
        _LOGGER.error("Failed to update transition validation: %s", e)
```

#### 1.3 `PersonLikelyNextRoomSensor` enhancement

The existing sensor in `sensor.py` already does `async_update` with a cached prediction. Add camera validation age as a new attribute to signal prediction reliability:

```python
# In async_update(), after getting _cached_prediction:
transit_validator = self.hass.data.get(DOMAIN, {}).get("transit_validator")
if transit_validator and self._cached_prediction:
    sighting = transit_validator.get_last_camera_sighting(self._person_id)
    self._last_camera_sighting = sighting

# In extra_state_attributes:
attrs = {
    "confidence": self._cached_prediction.get("confidence"),
    "sample_size": self._cached_prediction.get("sample_size"),
    "reliability": self._cached_prediction.get("reliability"),
    "alternatives": self._cached_prediction.get("alternatives"),
    "predicted_path": self._cached_prediction.get("predicted_path"),
    "current_room": self._cached_prediction.get("current_room", ""),
    # New in Cycle 6:
    "camera_last_seen": self._last_camera_sighting.get("timestamp") if self._last_camera_sighting else None,
    "camera_last_room": self._last_camera_sighting.get("room") if self._last_camera_sighting else None,
    "transit_camera_validated": self._last_camera_sighting is not None,
}
```

No change to native_value — prediction still comes from `pattern_learner`. Camera validation is an attribute only.

#### 1.4 Phone-left-behind sensor

New integration-level `binary_sensor` per tracked person. Disabled by default (diagnostic).

**Logic:**
- BLE says person X is in room Y
- Camera hasn't seen person X in any interior camera in N hours (configurable, default 4h)
- Room Y is a private room (no camera expected)
- Current time is outside sleep hours (22:00–07:00)

All three conditions must hold for `on`. Resets immediately when camera sees person X again.

**This is a diagnostic sensor only.** No automation should trigger from it without user confirming the signal is reliable in their specific home layout. Include a note in the sensor description attribute.

```python
class PersonPhoneLeftBehindSensor(AggregationEntity, BinarySensorEntity):
    """Diagnostic: BLE says person is home but camera hasn't seen them in hours.

    This is a best-effort signal. It is most reliable in homes where all
    interior shared spaces have cameras. It will produce false positives
    if a person spends extended time in a private room (bedroom/office).
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    PHONE_LEFT_BEHIND_HOURS: float = 4.0  # Hours without camera sighting
    SLEEP_START_HOUR: int = 22
    SLEEP_END_HOUR: int = 7

    def __init__(self, hass, entry, person_id: str) -> None: ...

    @property
    def is_on(self) -> bool | None:
        """Return True if phone-left-behind conditions are met."""
        # 1. Check sleep hours — suppress during sleep
        now = dt_util.now()
        hour = now.hour
        if hour >= self.SLEEP_START_HOUR or hour < self.SLEEP_END_HOUR:
            return False  # Suppress during sleep hours

        # 2. Check BLE location
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if not person_coordinator:
            return None
        person_data = person_coordinator.data.get(self._person_id, {})
        ble_location = person_data.get("location")
        if not ble_location or ble_location in ("unknown", "away"):
            return False  # Not home per BLE, not applicable

        # 3. Check camera sighting age
        transit_validator = self.hass.data.get(DOMAIN, {}).get("transit_validator")
        if not transit_validator:
            return None  # No camera data — can't determine
        sighting = transit_validator.get_last_camera_sighting(
            self._person_id,
            max_age_hours=self.PHONE_LEFT_BEHIND_HOURS,
        )
        return sighting is None  # True = no recent sighting = possible phone left behind

    @property
    def extra_state_attributes(self) -> dict:
        """Return diagnostic details."""
        ...
```

#### 1.5 Face recognition config toggle

A new config flow boolean controls whether face recognition data is used for identity validation.

- `CONF_FACE_RECOGNITION_ENABLED` (boolean, default `False`)
- When `False`, identity validation always returns `"unavailable"` — no face matching is attempted
- When `True`, `TransitValidator` uses face recognition data from camera events
- This allows homes without face recognition hardware/software to skip that logic entirely
- Graceful degradation: if enabled but no face data arrives, `identity_status = "unavailable"` (same as disabled)

---

### Section 2: Egress Directional Tracking

Egress cameras (configured via `CONF_EGRESS_CAMERAS`) see everyone who crosses an entry/exit point, but they don't inherently know the direction. Directional logic is determined by temporal correlation with interior cameras near that door.

**Logic:**

```
Egress camera fires:
  → Check if an interior camera near that door fired within ENTRY_WINDOW_SECONDS AFTER the egress event
     YES → Entry (person walked from outside through the door into interior)
     NO  → Check if an interior camera near that door fired within EXIT_WINDOW_SECONDS BEFORE the egress event
     YES → Exit (person walked from interior through the door to outside)
     NO  → Ambiguous (delivery/visitor who didn't enter; no interior camera fired at all)
```

Default windows: ENTRY_WINDOW_SECONDS = 45, EXIT_WINDOW_SECONDS = 30. These are conservative values. Entry window is longer because someone might pause at the door.

**Key constraint:** Directional tracking is probabilistic. "Ambiguous" events are recorded but not counted as entry or exit. The sensors reflect only confident determinations.

#### 2.1 New class in `transit_validator.py`: `EgressDirectionTracker`

Kept in the same file as `TransitValidator` since it also reads camera sighting data.

```python
class EgressDirectionTracker:
    """Correlate egress camera events with interior cameras to determine direction.

    Egress cameras are at: front door, garage doorbell, garage A, garage B.
    Interior near-door cameras are: foyer fisheye (near front door),
    staircase/garage hallway camera (near garage entry).
    """

    ENTRY_WINDOW_SECONDS = 45  # Look this far ahead for interior camera after egress
    EXIT_WINDOW_SECONDS = 30   # Look this far back for interior camera before egress
    AMBIGUOUS_COOLDOWN_SECONDS = 60  # Ignore subsequent ambiguous events within this window

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        # Recent egress events: {camera_entity_id: timestamp}
        self._recent_egress_events: dict[str, datetime] = {}
        # Recent interior-near-door events: {camera_entity_id: timestamp}
        self._recent_interior_events: dict[str, datetime] = {}

    async def async_init(self) -> None:
        """Subscribe to egress and near-door interior cameras."""

    async def _on_egress_camera_fired(
        self, egress_camera_id: str, timestamp: datetime
    ) -> None:
        """Handle egress camera detection.

        Schedules a direction resolution check after ENTRY_WINDOW_SECONDS.
        The check looks backward and forward to classify direction.
        """

    async def _resolve_direction(
        self, egress_camera_id: str, egress_timestamp: datetime
    ) -> str:
        """Determine entry, exit, or ambiguous.

        Returns: "entry" | "exit" | "ambiguous"
        """
        near_door_cameras = self._get_interior_cameras_near(egress_camera_id)

        for interior_cam in near_door_cameras:
            interior_time = self._recent_interior_events.get(interior_cam)
            if not interior_time:
                continue

            delta = (interior_time - egress_timestamp).total_seconds()

            if 0 <= delta <= self.ENTRY_WINDOW_SECONDS:
                return "entry"  # Interior fired after egress → entry
            if -self.EXIT_WINDOW_SECONDS <= delta < 0:
                return "exit"   # Interior fired before egress → exit

        return "ambiguous"

    def _get_interior_cameras_near(self, egress_camera_id: str) -> list[str]:
        """Return interior camera entity IDs physically adjacent to this egress camera.

        Mapping is derived from integration configuration. Users assign egress cameras
        at integration level; the room config tells us which rooms have cameras.
        The adjacency mapping is: egress camera entity → list of nearby interior camera entities.

        If no mapping exists, returns empty list → direction will always be "ambiguous"
        for this egress point, which is safe.
        """
```

#### 2.2 Integration data flow

`EgressDirectionTracker._resolve_direction()` fires `ura_person_egress_event` on the HA event bus:

```python
self.hass.bus.async_fire("ura_person_egress_event", {
    "direction": "entry" | "exit" | "ambiguous",
    "egress_camera": egress_camera_id,
    "timestamp": timestamp.isoformat(),
    "person_id": person_id_if_face_recognized,  # None if not identified
    "confidence": 0.0–1.0,
})
```

The warehoused sensors (Section 3) subscribe to this event to update their counters.

---

### Section 3: Warehoused Sensors

All six sensors that were explicitly warehoused in the Cycle 3 plan. They depend on Cycle 4 (census infrastructure) and Section 2 of this plan (egress directional tracking).

#### 3.1 Entry/Exit Count Sensors

**`sensor.ura_persons_entered_today`** — Count of confirmed entry events via egress cameras since midnight local time.

**`sensor.ura_persons_exited_today`** — Count of confirmed exit events since midnight.

Both reset at midnight. Both count all persons, identified and unidentified. "Confirmed" means direction was determined (`entry` or `exit`), not `ambiguous`.

On startup, each sensor restores today's count from the database to survive HA restarts. A `_restoring` flag prevents double-counting events that arrive during the restore window.

```python
class PersonsEnteredTodaySensor(AggregationEntity, SensorEntity):
    _attr_icon = "mdi:account-arrow-right"
    _attr_native_unit_of_measurement = "persons"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_persons_entered_today"
        self._attr_name = "Persons Entered Today"
        self._count = 0
        self._entries: list[dict] = []  # [{person_id, time, egress_camera}]
        self._last_reset = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self._restoring = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to egress events and restore today's count from DB."""
        self._restoring = True

        # Restore from database
        database = self.hass.data.get(DOMAIN, {}).get("database")
        if database:
            today_start = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
            events = await database.get_entry_exit_events_since(today_start, direction="entry")
            self._count = len(events)
            self._entries = events[-20:]  # Last 20 for attributes

        # Subscribe to live events
        self.hass.bus.async_listen("ura_person_egress_event", self._handle_egress_event)
        # Also subscribe to midnight reset
        async_track_time_change(self.hass, self._midnight_reset, hour=0, minute=0, second=0)

        self._restoring = False
        self.async_write_ha_state()

    @callback
    def _handle_egress_event(self, event) -> None:
        if self._restoring:
            return  # Already counted in DB restore
        if event.data.get("direction") != "entry":
            return
        self._count += 1
        self._entries.append({
            "person_id": event.data.get("person_id") or "unidentified",
            "time": event.data.get("timestamp"),
            "egress_camera": event.data.get("egress_camera"),
        })
        # Keep only today's entries (prune if clock drift)
        self.async_write_ha_state()

    @callback
    def _midnight_reset(self, now) -> None:
        self._count = 0
        self._entries = []
        self._last_reset = now
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        return self._count

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "entries": self._entries[-20:],  # Last 20 entries max
            "last_reset": self._last_reset.isoformat(),
        }
```

`PersonsExitedTodaySensor` is identical except it listens for `direction == "exit"` and queries `direction="exit"` on DB restore.

#### 3.2 Timestamp Sensors

**`sensor.ura_last_person_entry`** — Timestamp of the last confirmed entry event.

**`sensor.ura_last_person_exit`** — Timestamp of the last confirmed exit event.

These do not reset at midnight. They show the most recent entry/exit event regardless of date.

```python
class LastPersonEntrySensor(AggregationEntity, SensorEntity):
    _attr_icon = "mdi:account-arrow-right"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_last_person_entry"
        self._attr_name = "Last Person Entry"
        self._last_entry: datetime | None = None
        self._last_person_id: str | None = None
        self._last_egress_camera: str | None = None

    async def async_added_to_hass(self) -> None:
        self.hass.bus.async_listen("ura_person_egress_event", self._handle_egress_event)

    @callback
    def _handle_egress_event(self, event) -> None:
        if event.data.get("direction") != "entry":
            return
        self._last_entry = dt_util.parse_datetime(event.data.get("timestamp")) or dt_util.now()
        self._last_person_id = event.data.get("person_id") or "unidentified"
        self._last_egress_camera = event.data.get("egress_camera")
        self.async_write_ha_state()

    @property
    def native_value(self) -> datetime | None:
        return self._last_entry

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "person_id": self._last_person_id,
            "egress_camera": self._last_egress_camera,
        }
```

`LastPersonExitSensor` is the same with `direction == "exit"`.

#### 3.3 Census Mismatch Sensor

**`binary_sensor.ura_census_mismatch`** — `on` when the camera-visible person count and the BLE-tracked person count diverge significantly for an extended period.

**Logic:**
- Camera count = `sensor.ura_persons_in_house` (from Cycle 3 census)
- BLE count = number of tracked persons currently "home" per `person_coordinator`
- Mismatch = `|camera_count - ble_count| >= MISMATCH_THRESHOLD` (default: 2)
- Extended period = mismatch persists for `MISMATCH_DURATION_MINUTES` (default: 10 min)
- Only active when `sensor.ura_census_confidence` is not `"none"` (cameras must be working)

Purpose: catches cases where someone is home that URA doesn't know about, or a BLE device is home without its person. Feeds into v3.6.0 Security Coordinator as a data input.

```python
class CensusMismatchSensor(AggregationEntity, BinarySensorEntity):
    """On when camera count and BLE count diverge for an extended period."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_registry_enabled_default = True  # Enabled — useful for automations

    MISMATCH_THRESHOLD = 2        # Person count difference to trigger
    MISMATCH_DURATION_MINUTES = 10  # Must persist this long before sensor turns on

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_census_mismatch"
        self._attr_name = "Census Mismatch"
        self._mismatch_since: datetime | None = None
        self._camera_count: int = 0
        self._ble_count: int = 0

    @property
    def is_on(self) -> bool | None:
        # Get current counts
        census_state = self.hass.states.get("sensor.ura_persons_in_house")
        confidence_state = self.hass.states.get("sensor.ura_census_confidence")

        if not census_state or not confidence_state:
            return None
        if confidence_state.state == "none":
            return False  # No camera data — can't compare

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
        return {
            "camera_count": self._camera_count,
            "ble_count": self._ble_count,
            "mismatch_since": self._mismatch_since.isoformat() if self._mismatch_since else None,
            "threshold": self.MISMATCH_THRESHOLD,
            "duration_minutes": self.MISMATCH_DURATION_MINUTES,
        }
```

#### 3.4 Per-Zone Unidentified Count Sensors

**`sensor.{zone_name}_unidentified_count`** — Count of persons seen by cameras that cannot be matched to any known BLE or face-recognized person.

**Data availability constraint:** Cameras in v3.5.1 Slim are house-level — `PersonCensus` provides a total house count and the zone aggregation is driven by BLE, not per-zone camera data. There is no `census.get_zone_result(zone_id)` method and no per-zone camera count.

**Recommended approach (option a): use house-level data only.** The sensor reports the house-level unidentified count (camera total minus BLE identified total), clearly named to avoid implying zone-level precision. This is non-redundant with `ZoneGuestCountSensor` because it uses the camera count as the total rather than BLE presence.

If per-zone camera data becomes available in a future cycle, this sensor can be updated to use it. Until then, the name is `sensor.ura_unidentified_persons` (house-level, not per-zone).

> **Note:** The original per-zone framing has been removed. A single house-level sensor ships. The per-zone variant is deferred until per-zone camera data exists.

```python
class UnidentifiedPersonsSensor(AggregationEntity, SensorEntity):
    """House-level unidentified persons — camera sees them but BLE can't identify.

    Uses house-level camera count (PersonCensus) minus BLE identified count.
    Not per-zone: per-zone camera data does not exist in v3.5.1 Slim.
    """

    _attr_icon = "mdi:account-question"
    _attr_native_unit_of_measurement = "persons"
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{DOMAIN}_unidentified_persons"
        self._attr_name = "Unidentified Persons"

    @property
    def native_value(self) -> int | None:
        census_state = self.hass.states.get("sensor.ura_persons_in_house")
        if not census_state:
            return None
        try:
            camera_total = int(float(census_state.state))
        except (ValueError, TypeError):
            return None

        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if not person_coordinator:
            return None
        ble_identified = sum(
            1 for p in person_coordinator.data.values()
            if p.get("location") not in (None, "unknown", "away")
        )

        return max(0, camera_total - ble_identified)

    @property
    def extra_state_attributes(self) -> dict:
        census_state = self.hass.states.get("sensor.ura_persons_in_house")
        person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        camera_total = None
        ble_identified = None
        if census_state:
            try:
                camera_total = int(float(census_state.state))
            except (ValueError, TypeError):
                pass
        if person_coordinator:
            ble_identified = sum(
                1 for p in person_coordinator.data.values()
                if p.get("location") not in (None, "unknown", "away")
            )
        return {
            "camera_total": camera_total,
            "ble_identified": ble_identified,
            "data_scope": "house_level",
            "note": "Per-zone unidentified count deferred until per-zone camera data available",
        }
```

---

## ENTITIES

### New Entities (Enabled by Default)

| Entity ID | Type | Description |
|---|---|---|
| `sensor.ura_persons_entered_today` | sensor | Count of confirmed entries via egress cameras today |
| `sensor.ura_persons_exited_today` | sensor | Count of confirmed exits via egress cameras today |
| `sensor.ura_last_person_entry` | sensor (timestamp) | Timestamp of most recent confirmed entry |
| `sensor.ura_last_person_exit` | sensor (timestamp) | Timestamp of most recent confirmed exit |
| `binary_sensor.ura_census_mismatch` | binary_sensor (problem) | On when camera count and BLE count diverge for 10+ min |
| `sensor.ura_unidentified_persons` | sensor (house-level) | Unidentified persons house-wide from camera minus BLE count |

### New Entities (Disabled by Default — Diagnostic)

| Entity ID | Type | Description |
|---|---|---|
| `binary_sensor.{person_id}_phone_left_behind` | binary_sensor (problem) | BLE home but no camera sighting in 4+ hours |

### Modified Entities

| Entity ID | Change |
|---|---|
| `sensor.{person_id}_likely_next_room` | Adds `camera_last_seen`, `camera_last_room`, `transit_camera_validated` attributes |

### Entity Notes

- `sensor.ura_unidentified_persons` is house-level. Per-zone unidentified count is deferred until per-zone camera data is available (post-v3.5.2).
- `ura_census_mismatch` is enabled by default because it is actionable for automations, unlike the phone-left-behind sensor which is noisy.
- Entry/exit count sensors use `SensorStateClass.TOTAL_INCREASING` so HA energy dashboard handles them correctly. They reset at midnight via `async_track_time_change`, which is safe — HA handles total-increasing resets. They restore from the database on startup using a `_restoring` flag to prevent double-counting.
- The phone-left-behind sensor suppresses during sleep hours (configurable via existing `CONF_SLEEP_START_HOUR` / `CONF_SLEEP_END_HOUR` constants in const.py). This prevents false positives when someone goes to bed.
- Identity validation (`identity_status`) is a separate attribute on `TransitValidationResult` and does not affect transition confidence. It requires `CONF_FACE_RECOGNITION_ENABLED = True` to produce values other than `"unavailable"`.

---

## FILES TO CREATE/MODIFY

| File | Action | What Changes | Est. Lines |
|---|---|---|---|
| `transit_validator.py` | **Create** | `TransitValidator` (with `_get_shared_space_cameras()`, `_correlate_sighting_to_transition()`) + `EgressDirectionTracker` + updated dataclasses | ~320 |
| `transitions.py` | **Modify** | Wire in `TransitValidator`, add `_update_transition_confidence()`, add `set_transit_validator()`, update to use `path_confidence_delta` | ~40 |
| `database.py` | **Modify** | Add `update_transition_validation()` + `log_entry_exit_event()` + `get_entry_exit_events_since()` methods + `person_entry_exit_events` table + PRAGMA-based migration for `room_transitions` columns | ~100 |
| `sensor.py` | **Modify** | Add 4 integration-level sensors + house-level `UnidentifiedPersonsSensor` (replaces per-zone) + enrich `PersonLikelyNextRoomSensor` + DB restore in count sensors | ~220 |
| `binary_sensor.py` | **Modify** | Add `CensusMismatchSensor` + `PersonPhoneLeftBehindSensor` | ~120 |
| `__init__.py` | **Modify** | Init `TransitValidator`, `EgressDirectionTracker`, wire into `TransitionDetector` | ~30 |
| `const.py` | **Modify** | Add timing constants for transit validation, egress direction, and `CONF_FACE_RECOGNITION_ENABLED` | ~25 |

### New constants for `const.py`

```python
# v3.5.2 Transit Validation
TRANSIT_CHECKPOINT_STALE_SECONDS: Final = 90
TRANSIT_CHECKPOINT_WINDOW_SECONDS: Final = 120
TRANSIT_PHONE_LEFT_BEHIND_HOURS: Final = 4.0

# v3.5.2 Egress Direction Tracking
EGRESS_ENTRY_WINDOW_SECONDS: Final = 45
EGRESS_EXIT_WINDOW_SECONDS: Final = 30
EGRESS_AMBIGUOUS_COOLDOWN_SECONDS: Final = 60

# v3.5.2 Census Mismatch
CENSUS_MISMATCH_THRESHOLD: Final = 2       # person count difference
CENSUS_MISMATCH_DURATION_MINUTES: Final = 10  # minutes of sustained mismatch

# v3.5.2 Face Recognition
CONF_FACE_RECOGNITION_ENABLED: Final = "face_recognition_enabled"
```

### New database table and methods for `database.py`

**New table** (add to `initialize()` alongside existing tables):

```python
await db.execute("""
    CREATE TABLE IF NOT EXISTS person_entry_exit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME NOT NULL,
        person_id TEXT,
        event_type TEXT NOT NULL,
        direction TEXT NOT NULL,
        egress_camera TEXT NOT NULL,
        confidence REAL NOT NULL
    )
""")
await db.execute("""
    CREATE INDEX IF NOT EXISTS idx_entry_exit_timestamp
    ON person_entry_exit_events(timestamp)
""")
await db.execute("""
    CREATE INDEX IF NOT EXISTS idx_entry_exit_person
    ON person_entry_exit_events(person_id, timestamp)
""")
```

**New methods** on `UniversalRoomDatabase`:

```python
async def update_transition_validation(
    self,
    person_id: str,
    timestamp: datetime,
    new_confidence: float,
    validation_method: str,
    checkpoint_rooms: list[str],
) -> None:
    """Update confidence and validation metadata for a recorded transition."""
    try:
        async with aiosqlite.connect(self.db_file) as db:
            await db.execute("""
                UPDATE room_transitions
                SET confidence = ?,
                    validation_method = ?,
                    checkpoint_rooms = ?
                WHERE person_id = ?
                  AND timestamp = ?
            """, (
                new_confidence,
                validation_method,
                json.dumps(checkpoint_rooms),
                person_id,
                timestamp.isoformat(),
            ))
            await db.commit()
    except Exception as e:
        _LOGGER.error("Error updating transition validation: %s", e)

async def log_entry_exit_event(
    self,
    person_id: str | None,
    event_type: str,
    direction: str,
    egress_camera: str,
    confidence: float,
) -> None:
    """Log a confirmed entry or exit event."""
    try:
        async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
            await db.execute("""
                INSERT INTO person_entry_exit_events
                    (timestamp, person_id, event_type, direction, egress_camera, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.utcnow().isoformat(),
                person_id,
                event_type,
                direction,
                egress_camera,
                confidence,
            ))
            await db.commit()
    except Exception as e:
        _LOGGER.error("Error logging entry/exit event: %s", e)

async def get_entry_exit_events_since(
    self,
    since: datetime,
    direction: str,
) -> list[dict]:
    """Return entry or exit events since the given datetime.

    Used by count sensors on startup to restore today's count from DB.
    Returns a list of dicts with keys: person_id, timestamp, egress_camera.
    """
    try:
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT person_id, timestamp, egress_camera
                FROM person_entry_exit_events
                WHERE timestamp >= ?
                  AND direction = ?
                ORDER BY timestamp ASC
            """, (since.isoformat(), direction))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        _LOGGER.error("Error fetching entry/exit events: %s", e)
        return []
```

Note: The `room_transitions` table needs two new columns to support transit validation. These are added as nullable columns via `ALTER TABLE` (not a schema rebuild) in `initialize()` so existing databases upgrade cleanly. A PRAGMA check is used instead of a bare try/except to avoid silently swallowing real errors:

```python
# In initialize(), migration-safe column additions:
async with aiosqlite.connect(self.db_file) as db:
    cursor = await db.execute("PRAGMA table_info(room_transitions)")
    columns = {row[1] for row in await cursor.fetchall()}

    if "validation_method" not in columns:
        await db.execute(
            "ALTER TABLE room_transitions ADD COLUMN validation_method TEXT"
        )
    if "checkpoint_rooms" not in columns:
        await db.execute(
            "ALTER TABLE room_transitions ADD COLUMN checkpoint_rooms TEXT"
        )
    await db.commit()
```

### `__init__.py` initialization additions

After `transition_detector.async_init()` in the existing v3.3.0 block:

```python
# v3.5.2: Transit validation and egress direction tracking
try:
    from .transit_validator import TransitValidator, EgressDirectionTracker

    transit_validator = TransitValidator(hass)
    await transit_validator.async_init()
    hass.data[DOMAIN]["transit_validator"] = transit_validator

    # Wire validator into transition detector
    transition_detector.set_transit_validator(transit_validator)

    egress_tracker = EgressDirectionTracker(hass)
    await egress_tracker.async_init()
    hass.data[DOMAIN]["egress_tracker"] = egress_tracker

    _LOGGER.info("Transit validation and egress direction tracking initialized")
except Exception as e:
    _LOGGER.warning(
        "Transit validation init failed — sensor predictions will work without camera enrichment: %s", e
    )
    # Non-fatal: TransitionDetector still works, TransitValidator simply won't be wired in
```

---

## VERIFICATION

### Functional checks

1. **No cameras configured** — All warehoused sensors exist but show 0 / `None`. `CensusMismatchSensor` returns `False` (not `on`). No errors in logs. `PersonLikelyNextRoomSensor` attributes show `transit_camera_validated: false`. Integration behaves identically to Cycle 4.

2. **Egress camera fires, interior near-door camera fires within 45 seconds** — `ura_person_egress_event` fires with `direction: "entry"`. `sensor.ura_persons_entered_today` increments. `sensor.ura_last_person_entry` updates to current time.

3. **Interior near-door camera fires, egress camera fires within 30 seconds** — Event fires with `direction: "exit"`. `sensor.ura_persons_exited_today` increments.

4. **Egress camera fires, no interior camera fires** — Event fires with `direction: "ambiguous"`. Neither count sensor increments.

5. **Midnight rollover** — `sensor.ura_persons_entered_today` and `sensor.ura_persons_exited_today` reset to 0. `sensor.ura_last_person_entry` and `sensor.ura_last_person_exit` retain their last values (they don't reset).

6. **HA restart mid-day** — Count sensors query `get_entry_exit_events_since(today_start)` during `async_added_to_hass()`. `_restoring = True` during the query. Events that arrive during restore are dropped. After restore completes, `_restoring = False` and live events are counted normally. Count reflects correct today total.

7. **BLE says 2 persons home, camera sees 4 for 11 minutes** — `binary_sensor.ura_census_mismatch` turns `on`. Attributes show `camera_count: 4`, `ble_count: 2`, `mismatch_since: <timestamp>`.

8. **Census mismatch clears** — Camera count drops to 2 (guests left). `binary_sensor.ura_census_mismatch` turns `off`. `mismatch_since` clears.

9. **Transit validation: BLE records transition, hallway camera fired in window** — `room_transitions` table row gets `confidence` boosted by +0.10 and `validation_method: "path_plausible"`. `sensor.{person}_likely_next_room` shows `transit_camera_validated: true`.

10. **Transit validation: BLE records transit, path cameras active but did not fire** — Confidence decremented by -0.15. `validation_method: "path_implausible"`. `identity_status: "unavailable"` (face recognition disabled by default).

11. **Multi-person transit: two BLE transitions within 30 seconds, one shared-space camera sighting** — `_correlate_sighting_to_transition()` assigns `path_plausible` to the closer-timed transition; the other gets `no_camera_data` (confidence unchanged, not penalized).

12. **Multi-person transit: two BLE transitions to same room within 60 seconds, camera saw 2 people** — Both transitions get `path_plausible`.

13. **Face recognition enabled, camera confirms identity** — `identity_status: "confirmed"`, `camera_person_id` matches BLE person ID. No confidence delta from identity alone.

14. **Face recognition disabled (default)** — `identity_status: "unavailable"` regardless of camera data. Path validation still operates normally.

15. **Phone-left-behind: John's BLE is in bedroom, no camera sighting in 4.5 hours, not sleep hours** — `binary_sensor.john_phone_left_behind` turns `on`. Attributes show `ble_location: bedroom`, `hours_since_camera_sighting: 4.5`.

16. **Phone-left-behind: sleep hours active (22:00–07:00)** — Sensor returns `off` regardless of camera sighting age.

17. **Unidentified persons: camera sees 3 total, 2 BLE identified persons home** — `sensor.ura_unidentified_persons` = 1. Attributes show `data_scope: "house_level"`.

18. **Database migration: existing installation upgrading from Cycle 4** — PRAGMA check reads `room_transitions` columns; `ALTER TABLE` runs only if `validation_method` or `checkpoint_rooms` are absent. No error on repeat startup (columns already exist, PRAGMA check skips ALTER). `person_entry_exit_events` table created fresh.

---

## DEPLOY

```bash
./scripts/deploy.sh "3.5.2" "Transit validation and warehoused sensors" "- TransitValidator: path validation via shared-space cameras (no per-room topology required)
- _correlate_sighting_to_transition(): multi-person transit attribution by face ID then timing
- TransitValidationResult: path validation and identity validation as separate concerns
- EgressDirectionTracker: egress camera + interior camera correlation for entry/exit direction
- CONF_FACE_RECOGNITION_ENABLED: toggle for identity validation (default False)
- sensor.ura_persons_entered_today / exited_today with midnight reset + DB restore on startup
- sensor.ura_last_person_entry / last_person_exit (timestamp sensors)
- binary_sensor.ura_census_mismatch (camera vs BLE count divergence, 10-min sustain)
- sensor.ura_unidentified_persons (house-level; per-zone deferred)
- binary_sensor.{person}_phone_left_behind (diagnostic, disabled by default)
- PersonLikelyNextRoomSensor enriched with camera validation attributes
- person_entry_exit_events database table + get_entry_exit_events_since() for DB restore
- room_transitions: validation_method + checkpoint_rooms columns via PRAGMA-checked ALTER TABLE"
```

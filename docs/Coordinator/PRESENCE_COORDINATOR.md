# PRESENCE COORDINATOR DESIGN

**Version:** 1.0  
**Status:** Design Complete  
**Last Updated:** 2026-01-24  
**Scope:** House-level state inference and management

---

## ADDENDUM — Occupancy substrate (unified Tier-1 raw-signal layer)

The `OccupancySubstrate`
(`custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py`)
is a sensor-layer abstraction that sits **BENEATH** the room
(`RoomCoordinator` / `coordinator.py`) and zone (`ZonePresenceTracker` /
`presence.py`) tiers. It is **NOT a new tier and does NOT replace either
of the existing room or zone tiers** — both tiers continue to apply
their own legitimate temporal smoothing (room: 900s timeout / failsafe /
camera + BLE override; zone: derived OR over `_room_provenance`,
`raw_occupied`, fan-interference hold, camera timeout, BLE precedence)
on top of the substrate's instantaneous per-room, per-kind raw view.

What the substrate unifies:

* **Discovery.** Sources entities exclusively from the operator's curated
  `CONF_MOTION_SENSORS` / `CONF_MMWAVE_SENSORS` / `CONF_OCCUPANCY_SENSORS`
  per-room lists. NO entity-registry area-sweep, NO substring name
  heuristic.
* **Classification.** Kind ∈ `TIER1_KINDS` is determined by which CONF
  list slot the entity is in, with precedence motion → mmwave → occupancy
  for the defensive case of multi-list membership.
* **Capability vs. role (SENSOR-CAPABILITY-1, 2026-08-09).** The three
  CONF lists remain the WIRING declaration. A separate CAPABILITY layer
  (`domain_coordinators/sensor_capability.py`) tags each entity with a
  richer kind (`bed` / `camera_presence` / `ble_presence` / … — a
  superset of `TIER1_KINDS`) and a `trust_class` /`failure_mode`; the
  operator declares only ambiguous cases via `CONF_SENSOR_CAPABILITIES`
  and every other entity's capability derives 1:1 from CONF membership
  so behaviour is byte-identical (I1) until a declaration exists.
  ROLE is a computed function of the QUESTION and is resolved at the
  CONSUMPTION site via `domain_coordinators/sensor_role.resolve_role`
  (`RoleQuery` = CANDIDATE_FOR_STUCK / CORROBORATOR_FOR_ROOM /
  CREATOR_VS_EXTENDER). TIER1_KINDS itself is UNCHANGED — extending it
  would trip `_audit_provenance_invariants` (I3) and pay O(N-sites)
  blast radius per new kind. Consumption-site resolution bounds new
  capabilities to O(1). First in-cycle consumer: D2 duty-cycle
  detector (`coordinator._detect_duty_cycle_stuck`).
* **Subscription.** One `async_track_state_change_event` listener per
  discovered entity — both tiers consume from the substrate (room tier
  via `SIGNAL_SUBSTRATE_KIND_CHANGED` in `coordinator.py`; zone tier via
  the same signal in `presence.py:_on_substrate_kind_changed`).
* **Publishing.** Per-kind edges emit `SIGNAL_SUBSTRATE_KIND_CHANGED(room,
  kind, new_state)`. Suppressed while the PresenceCoordinator's
  `_boot_settle_done` gate is False; `_raw_state` is still updated, and a
  synthetic dispatch per True-slot fires at settle (False slots emit
  nothing — consumers default False).

The room tier's smoothing pipeline in
`UniversalRoomCoordinator._async_update_data` is unchanged — the
substrate only changes WHERE the Tier-1 listener edge originates. The
zone tier's `raw_occupied` semantics (the v4.7.18.1 wake-timer
dependency) and the `_room_provenance` shape are preserved.

---

## ADDENDUM — HOUSE-zone "away" mechanism (`ZonePresenceTracker._derived_mode`)

**Added 2026-08-17 (audit `AUDIT_zone_away_house_vs_hvac.md`, absence finding).**
This is the single most load-bearing house-zone-away logic and was previously
undocumented. Keep the **HOUSE zone vs HVAC zone** distinction crisp: a HOUSE zone
is a presence grouping (Back Hallway, Master Suite, "Outside") with a per-zone mode
on `ZonePresenceTracker`; an **HVAC zone** is thermostat-keyed (`zone_N`) and one
HVAC zone maps to MULTIPLE house zones by design (memory
`project_house_zones_vs_hvac_zones`). HVAC-zone occupancy is a **separate
derivation** (room-level `occupied` bools) documented in the HVAC coordinator
manual — do not conflate it with this tracker.

A house zone's published mode is `ZonePresenceTracker.mode` (`presence.py:597-601`):
it returns the manual `_override` if one is set (AWAY/OCCUPIED/SLEEP via the Zone
Presence Override select), else the computed `_derived_mode`.

`_derived_mode` (`presence.py:702-730`) is a **three-tier OR** — any single positive
tier holds the zone OCCUPIED; AWAY is simply the absence of all three:

1. **Tier 3 — BLE / phone location (checked FIRST, ungated).** `if
   self._ble_occupied: return OCCUPIED` (`presence.py:710-711`). Evaluated before
   the others and NOT gated on sensor discovery, because BLE person-location is the
   most reliable signal. Fed by `_update_ble_zone_presence` — a Bermuda room-resolved
   person location mapped up to the zone.
2. **Tier 1 — room occupancy sensors (mmWave / PIR / occupancy).** `if
   any(self._room_occupied.values()): return OCCUPIED` (`presence.py:716-717`), gated
   on `self._has_sensors`. `_room_occupied` is the provenance-split OR over
   `_room_provenance` plus the fan-interference hold, which can only EXTEND occupancy.
3. **Tier 2 — camera person/motion with timeout.** `if self._any_camera_occupied():
   return OCCUPIED` (`presence.py:720-721`).
4. Else **AWAY** (`presence.py:723`); UNKNOWN only when no sensors were ever
   discovered and no BLE was ever seen (`presence.py:730`).

**Key property — no input can force a zone AWAY against a positive signal.** The
tiers are a pure OR: BLE, room sensors, and camera each only ever vote OCCUPIED.
Nothing drives a zone to AWAY against a positive tier. The **only** hard override is
the manual `_override`, which beats all tiers (`presence.py:598-600`).

Zone modes aggregate up to `any_zone_occupied` (and the outdoor-excluded
`any_indoor_zone_occupied`), which are the INPUTS the house-STATE away paths consume
(§3). House-STATE away does not feed back into per-zone mode except for SLEEP-hours
masking of the tracker mode.

---

## TABLE OF CONTENTS

1. [Overview](#1-overview)
2. [House States](#2-house-states)
3. [State Inference Engine](#3-state-inference-engine)
4. [State Machine](#4-state-machine)
5. [Inputs](#5-inputs)
6. [Outputs](#6-outputs)
7. [Integration with Census](#7-integration-with-census)
8. [Manual Overrides](#8-manual-overrides)
9. [Implementation](#9-implementation)
10. [Sensors & Services](#10-sensors--services)
11. [Diagnostics](#11-diagnostics)

---

## 1. OVERVIEW

### Purpose

The Presence Coordinator **infers and manages house-level state** based on:
- Census data (who's where)
- Time of day
- Entry/exit patterns
- Activity levels
- Manual overrides

It is the **foundation layer** that all other coordinators depend on.

### What It Is NOT

| Not This | That's This |
|----------|-------------|
| Person tracking | Census (URA 3.5) |
| Per-room occupancy | Room automations |
| Security decisions | Security Coordinator |
| Energy decisions | Energy Coordinator |

### Key Principle

**Presence Coordinator provides STATE, not ACTIONS.**

It answers: "What mode is the house in?"  
Other coordinators decide: "What should I do about it?"

---

## 2. HOUSE STATES

### State Definitions

```python
class HouseState(Enum):
    """
    Possible states of the house.
    
    These represent the OVERALL mode of the household,
    not individual room states.
    """
    
    AWAY = "away"
    # Nobody home. House in conservation mode.
    # Security: Full arm
    # Energy: Maximum conservation
    # HVAC: Away presets, wide setbacks
    
    ARRIVING = "arriving"  
    # Someone coming home (geofence, garage, door).
    # Transitional state - prepare house for occupancy.
    # Security: Disarm entry path
    # Energy: Pre-condition house
    # HVAC: Begin bringing to comfort
    
    HOME_DAY = "home_day"
    # People home during daytime hours (roughly 6am-5pm).
    # Full comfort, normal operations.
    # Security: Disarmed
    # Energy: Normal with TOU awareness
    # HVAC: User preferences
    
    HOME_EVENING = "home_evening"
    # People home during evening (roughly 5pm-9pm).
    # Active household, family time.
    # Security: Perimeter monitoring
    # Energy: Normal with TOU awareness
    # HVAC: User preferences
    
    HOME_NIGHT = "home_night"
    # People home, winding down (roughly 9pm-11pm).
    # Transition toward sleep.
    # Security: Perimeter + interior paths
    # Energy: Prepare for overnight
    # HVAC: Begin transition to sleep temps
    
    SLEEP = "sleep"
    # Household sleeping.
    # Minimal disturbance, overnight mode.
    # Security: Full home arm (interior + perimeter)
    # Energy: Overnight mode
    # HVAC: Sleep presets, limited adjustments
    
    WAKING = "waking"
    # Morning transition (alarm time to ~1hr after).
    # Gradually activate house.
    # Security: Disarming
    # Energy: Morning preparation
    # HVAC: Wake presets, warm up
    
    GUEST = "guest"
    # Non-family visitors present.
    # Modified behavior - less personalization.
    # Security: Modified arm (guest areas OK)
    # Energy: Less aggressive conservation
    # HVAC: All zones comfortable
    
    VACATION = "vacation"
    # Extended away (manual set or detected).
    # Maximum conservation + security.
    # Security: Enhanced monitoring
    # Energy: Maximum conservation
    # HVAC: Deep setbacks
    
    EMERGENCY = "emergency"
    # Active safety or security event.
    # Override all normal operations.
    # All systems defer to Safety/Security coordinators
```

### State Characteristics

| State | Typical Duration | Auto-Inferred | Manual Set |
|-------|------------------|---------------|------------|
| AWAY | Hours to days | Yes | Yes |
| ARRIVING | 5-15 minutes | Yes | No |
| HOME_DAY | Hours | Yes | No |
| HOME_EVENING | 3-5 hours | Yes | No |
| HOME_NIGHT | 1-2 hours | Yes | No |
| SLEEP | 6-9 hours | Yes | Yes |
| WAKING | 30-60 minutes | Yes | No |
| GUEST | Hours | Partial | Yes |
| VACATION | Days | Partial | Yes |
| EMERGENCY | Minutes | Yes | No |

---

## 3. STATE INFERENCE ENGINE

### Inference Inputs

> **Updated 2026-08-17 (audit `AUDIT_zone_away_house_vs_hvac.md`).** The prior
> `PresenceContext` / `_infer_empty_house` / `total_occupants` pseudocode in this
> section no longer resembled the implementation and was removed. The real engine
> is `StateInferenceEngine.infer()` (`presence.py:981-1208`), a keyword-argument
> method — not a `PresenceContext` dataclass — whose load-bearing away logic is the
> three away branches described below. See §3 ("Interaction with the house-STATE
> AWAY paths") for the full treatment of the away vetoes and the LOST evidence
> matrix.

`StateInferenceEngine.infer()` (`presence.py:981`) takes, among others,
`census_count`, `current_state`, `any_zone_occupied`, `unidentified_count`,
`all_tracked_persons_away`, `face_recognized_count`, and the v5.7.0 path-β
keyword args (`all_trusted_or_lost_away_persons_away`, `any_indoor_zone_occupied`,
`grace_elapsed_for_lost_away`, `lost_away_persons_present`, `sleep_exempt_state`,
`sustained_external_empty`). It returns `Optional[HouseState]` (None = no change),
and sets `self._confidence` / `self._veto_path` as side effects.

The three explicit AWAY branches, in evaluation order:

1. **Base "nobody home"** — `presence.py:1059-1063`: `census_count == 0 AND not
   any_zone_occupied` → `HouseState.AWAY`, confidence **0.9**. Room sensors (via
   `any_zone_occupied`) and census are both hard gates.
2. **Path α — phones confidently away** — `presence.py:1091-1101`:
   `all_tracked_persons_away AND unidentified_count == 0 AND
   face_recognized_count == 0` → AWAY, confidence **0.95**. Ignores room sensors.
3. **Path β — a phone is LOST/uncertain** — `presence.py:1168-1208`:
   LOST-admitted denominator + `not indoor_blocked AND census_count == 0` + grace
   clock / immediate-engage / sleep exemption → AWAY, confidence **0.95**. Respects
   room sensors.

If none fire and `census_count > 0 or any_zone_occupied`, the house is occupied and
the engine resolves ARRIVING / SLEEP / WAKING / HOME_* / GUEST variants downstream
(`presence.py:1210+`). Emergency and manual vacation/guest overrides are applied by
the `PresenceCoordinator` caller, not inside `infer()`.

### Confidence Factors

| Factor | Increases Confidence | Decreases Confidence |
|--------|---------------------|---------------------|
| Census reliability | High person certainty | Unknown persons |
| Time alignment | State matches time | State mismatches time |
| Pattern match | Matches historical | Unusual for this time |
| Activity consistency | Activity matches state | Activity contradicts |
| Duration | Stable for expected time | Too short/long |

---

## 4. STATE MACHINE

### Transition Rules

```python
class HouseStateMachine:
    """Manage state transitions with validation."""
    
    # Valid transitions from each state
    VALID_TRANSITIONS = {
        HouseState.AWAY: {
            HouseState.ARRIVING,    # Someone coming home
            HouseState.VACATION,    # Detected extended absence
            HouseState.EMERGENCY,   # Safety/security event
        },
        HouseState.ARRIVING: {
            HouseState.HOME_DAY,    # Arrived during day
            HouseState.HOME_EVENING,# Arrived during evening
            HouseState.HOME_NIGHT,  # Arrived late
            HouseState.AWAY,        # False positive, left again
            HouseState.EMERGENCY,
        },
        HouseState.HOME_DAY: {
            HouseState.HOME_EVENING,# Time progression
            HouseState.AWAY,        # Everyone left
            HouseState.GUEST,       # Visitors arrived
            HouseState.EMERGENCY,
        },
        HouseState.HOME_EVENING: {
            HouseState.HOME_NIGHT,  # Time progression
            HouseState.HOME_DAY,    # Weekend, back to day activities
            HouseState.AWAY,        # Everyone left
            HouseState.GUEST,       # Visitors arrived
            HouseState.EMERGENCY,
        },
        HouseState.HOME_NIGHT: {
            HouseState.SLEEP,       # Bedtime
            HouseState.HOME_EVENING,# Still active
            HouseState.AWAY,        # Everyone left (unusual)
            HouseState.EMERGENCY,
        },
        HouseState.SLEEP: {
            HouseState.WAKING,      # Morning
            HouseState.HOME_NIGHT,  # Someone got up
            HouseState.EMERGENCY,
        },
        HouseState.WAKING: {
            HouseState.HOME_DAY,    # Fully awake
            HouseState.AWAY,        # Left for work
            HouseState.SLEEP,       # Back to bed (weekend)
            HouseState.EMERGENCY,
        },
        HouseState.GUEST: {
            HouseState.HOME_DAY,    # Guests left
            HouseState.HOME_EVENING,# Guests left
            HouseState.AWAY,        # Everyone left
            HouseState.EMERGENCY,
        },
        HouseState.VACATION: {
            HouseState.ARRIVING,    # Coming back
            HouseState.AWAY,        # Downgrade from vacation
            HouseState.EMERGENCY,
        },
        HouseState.EMERGENCY: {
            # Can transition to anything when emergency clears
            HouseState.AWAY,
            HouseState.HOME_DAY,
            HouseState.HOME_EVENING,
            HouseState.HOME_NIGHT,
            HouseState.SLEEP,
        },
    }
    
    # Minimum time in state before allowing transition (hysteresis)
    MIN_DURATION = {
        HouseState.ARRIVING: timedelta(minutes=5),
        HouseState.WAKING: timedelta(minutes=15),
        HouseState.SLEEP: timedelta(minutes=30),
        HouseState.GUEST: timedelta(hours=1),
        HouseState.HOME_NIGHT: timedelta(minutes=30),
    }
    
    # Minimum confidence to transition
    MIN_CONFIDENCE = {
        HouseState.SLEEP: 0.75,       # Higher bar for sleep
        HouseState.EMERGENCY: 0.60,   # Lower bar for emergency (safety)
        HouseState.VACATION: 0.80,    # Higher bar for vacation
    }
    DEFAULT_MIN_CONFIDENCE = 0.70
    
    def __init__(self):
        self._current_state = HouseState.AWAY
        self._state_entered_at = datetime.now()
        self._confidence = 0.5
    
    def try_transition(
        self, 
        new_state: HouseState, 
        confidence: float
    ) -> bool:
        """
        Attempt state transition.
        
        Returns True if transition occurred.
        """
        # Same state - just update confidence
        if new_state == self._current_state:
            self._confidence = confidence
            return False
        
        # Validate transition is allowed
        if new_state not in self.VALID_TRANSITIONS.get(self._current_state, set()):
            _LOGGER.warning(
                f"Invalid transition: {self._current_state} → {new_state}"
            )
            return False
        
        # Check minimum duration (hysteresis)
        min_duration = self.MIN_DURATION.get(
            self._current_state, 
            timedelta(minutes=1)
        )
        current_duration = datetime.now() - self._state_entered_at
        
        if current_duration < min_duration:
            # Exception: Emergency can always happen
            if new_state != HouseState.EMERGENCY:
                _LOGGER.debug(
                    f"Transition blocked by hysteresis: "
                    f"{current_duration} < {min_duration}"
                )
                return False
        
        # Check minimum confidence
        min_confidence = self.MIN_CONFIDENCE.get(
            new_state, 
            self.DEFAULT_MIN_CONFIDENCE
        )
        
        if confidence < min_confidence:
            _LOGGER.debug(
                f"Transition blocked by confidence: "
                f"{confidence:.0%} < {min_confidence:.0%}"
            )
            return False
        
        # Transition approved
        old_state = self._current_state
        self._current_state = new_state
        self._state_entered_at = datetime.now()
        self._confidence = confidence
        
        _LOGGER.info(
            f"House state: {old_state.name} → {new_state.name} "
            f"({confidence:.0%} confidence)"
        )
        
        return True
    
    @property
    def current_state(self) -> HouseState:
        return self._current_state
    
    @property
    def confidence(self) -> float:
        return self._confidence
    
    @property
    def state_duration(self) -> timedelta:
        return datetime.now() - self._state_entered_at
```

---

## 5. INPUTS

### From Census (URA 3.5)

```python
# Census signals we subscribe to
SIGNAL_CENSUS_UPDATED = "ura_census_updated"

# Census data structure
@dataclass
class CensusData:
    total_occupants: int
    persons: list[PersonLocation]
    room_occupancy: dict[str, list[str]]  # room_id -> [person_ids]


@dataclass
class PersonLocation:
    person_id: str
    current_room: str
    confidence: float
    last_seen: datetime
    is_known: bool  # True for family, False for unknown
```

### From Entry Sensors

| Entity Pattern | Purpose |
|----------------|---------|
| `binary_sensor.front_door_*` | Front door entry |
| `binary_sensor.garage_door_*` | Garage entry |
| `binary_sensor.back_door_*` | Back door entry |
| `cover.garage_*` | Garage door state |

### From Geofencing

| Entity Pattern | Purpose |
|----------------|---------|
| `device_tracker.phone_*` | Person location zones |
| `person.*` | HA person entities |

### Time Triggers

| Trigger | Purpose |
|---------|---------|
| Every 5 minutes | Re-evaluate state |
| At configured sleep time | Prompt sleep transition |
| At configured wake time | Prompt waking transition |

### Tier-1 provenance (provenance-split cycle)

`ZonePresenceTracker._room_provenance: Dict[str, Dict[str, bool]]` keys
each room to a per-kind dict where `kind ∈ TIER1_KINDS = ("motion",
"mmwave", "occupancy")`. The legacy `_room_occupied` view is preserved as
a derived `@property` returning `{room: any(provenance[room].values())}`
so all 22 SAFE consumers in the audit's Appendix A.2 read the same shape
unchanged.

Per-kind classification of firing entities is performed by the module-
level helper `_classify_entity_kind(hass, entity_id, room_name)` which is
the SINGLE classification source for BOTH the seed loop and the live
state-change callback (Bug Class #1 guard — seed vs live divergence).
The helper consults each owning room ConfigEntry's CONF_MMWAVE_SENSORS /
CONF_MOTION_SENSORS / CONF_OCCUPANCY_SENSORS lists, falling back to the
entity-id substring vocabulary already used in discovery
(`mmwave`/`presence` → mmwave, `motion` → motion, else `occupancy`).

The fan-interference Layer-1 diagnostic
(`_compute_fan_interference_rooms`) is observation-only; it surfaces a
per-tick "fan_interference_rooms" flag list via `signal_consensus_inputs`
without altering consensus arithmetic or zone-tracker `mode` output.

References:
- `docs/planning/AUDIT_presence_provenance.md` (GREEN audit verdict)
- `docs/planning/PLANNING_presence_provenance_split_and_fan_diagnostic.md`
- `docs/planning/PLANNING_presence_fan_actuation_and_ble_ladder_deferred.md`
  (deferred Layer-2/Layer-3 + PIR fusion)

---

## 6. OUTPUTS

### House State Entity

```yaml
sensor.ura_house_state:
  state: "HOME_EVENING"
  attributes:
    confidence: 0.92
    duration_minutes: 135
    previous_state: "HOME_DAY"
    entered_at: "2026-01-24T17:15:00"
    occupants: ["oji", "spouse"]
    occupant_count: 2
    is_manual_override: false
    next_expected_transition: "HOME_NIGHT"
    next_transition_time: "2026-01-24T21:00:00"
```

### State Change Events

```python
# Published via dispatcher signal
SIGNAL_HOUSE_STATE_CHANGED = "ura_house_state_changed"

# Event data
{
    "state": HouseState.HOME_EVENING,
    "previous_state": HouseState.HOME_DAY,
    "confidence": 0.92,
    "timestamp": "2026-01-24T17:15:00",
    "trigger": "time_progression",  # or "census_change", "manual", etc.
}
```

### Binary Sensors

```yaml
binary_sensor.ura_house_occupied:
  state: "on"  # Someone is home
  device_class: occupancy

binary_sensor.ura_house_sleeping:
  state: "off"
  device_class: occupancy

binary_sensor.ura_house_guest_mode:
  state: "off"
```

---

## 7. INTEGRATION WITH CENSUS

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CENSUS → PRESENCE INTEGRATION                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  CENSUS (URA 3.5)                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Person Tracking                                                     │    │
│  │  • Bermuda BLE triangulation                                        │    │
│  │  • Room transition detection                                        │    │
│  │  • Person identification                                            │    │
│  │                                                                     │    │
│  │  Publishes: census_updated events                                  │    │
│  │  Contains: who is where, with confidence                           │    │
│  └──────────────────────────────────┬──────────────────────────────────┘    │
│                                     │                                        │
│                                     ▼                                        │
│  PRESENCE COORDINATOR                                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Subscribes to census_updated                                       │    │
│  │  ↓                                                                  │    │
│  │  Aggregates: total occupants, known vs unknown                     │    │
│  │  ↓                                                                  │    │
│  │  Combines with: time, patterns, activity                           │    │
│  │  ↓                                                                  │    │
│  │  Infers: house_state                                               │    │
│  │  ↓                                                                  │    │
│  │  Publishes: house_state_changed                                    │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Census Event Handling

```python
class PresenceCoordinator(BaseCoordinator):
    
    COORDINATOR_ID = "presence"
    PRIORITY = 60
    
    async def async_setup(self) -> None:
        """Setup presence coordinator."""
        
        # Subscribe to Census updates
        async_dispatcher_connect(
            self.hass,
            SIGNAL_CENSUS_UPDATED,
            self._on_census_update,
        )
        
        # Entry point sensors
        for entity_id in self._entry_sensors:
            self.register_state_trigger(
                entity_id=entity_id,
                intent_type="entry_event",
                condition=lambda old, new: new.state == "on",
            )
        
        # Periodic re-evaluation
        self.register_time_trigger(
            interval=timedelta(minutes=5),
            intent_type="periodic_reevaluate",
        )
    
    async def _on_census_update(self, data: dict) -> None:
        """Handle Census update."""
        await self.manager.queue_intent(Intent(
            coordinator=self.COORDINATOR_ID,
            type="census_changed",
            data=data,
        ))
```

---

## 8. MANUAL OVERRIDES

### Override Services

```python
# Services exposed for manual control

async def async_set_house_state(
    self, 
    state: str, 
    duration_hours: float | None = None
) -> None:
    """
    Manually set house state.
    
    Used for:
    - "We're having a party" → GUEST
    - "We're going on vacation" → VACATION
    - "Everyone go to bed" → SLEEP
    """
    new_state = HouseState(state)
    
    self._manual_override = ManualOverride(
        state=new_state,
        set_at=datetime.now(),
        expires_at=(
            datetime.now() + timedelta(hours=duration_hours)
            if duration_hours else None
        ),
    )
    
    # Force transition
    self._state_machine.force_transition(new_state, confidence=0.99)
    
    _LOGGER.info(f"Manual override: {new_state.name}")


async def async_clear_override(self) -> None:
    """Clear manual override, return to auto-inference."""
    self._manual_override = None
    
    # Re-evaluate state
    await self._reevaluate_state()
```

### Override UI

```yaml
# Input select for manual state
input_select.house_state_override:
  name: House State Override
  options:
    - "Auto"
    - "Guest Mode"
    - "Vacation Mode"
    - "Sleep Mode"
  initial: "Auto"
  icon: mdi:home-account
```

---

## 9. IMPLEMENTATION

### Main Coordinator Class

```python
class PresenceCoordinator(BaseCoordinator):
    """
    House state inference and management.
    
    Foundation coordinator - all others depend on house state.
    """
    
    COORDINATOR_ID = "presence"
    PRIORITY = 60
    
    def __init__(self, hass: HomeAssistant, manager: CoordinatorManager):
        super().__init__(hass, manager)
        
        self._inference_engine = StateInferenceEngine()
        self._state_machine = HouseStateMachine()
        self._manual_override: ManualOverride | None = None
        
        # Cache Census data
        self._census_data: CensusData | None = None
        self._last_census_update: datetime | None = None
        
        # Activity tracking
        self._last_activity_time = datetime.now()
        self._activity_level = 0.5
        
        # Entry tracking
        self._last_entry_event: datetime | None = None
        self._was_empty_before_entry = False
    
    async def evaluate(
        self,
        intents: list[Intent],
        context: CoordinatorContext,
    ) -> list[CoordinatorAction]:
        """Evaluate intents and update house state."""
        
        actions = []
        
        for intent in intents:
            if intent.type == "census_changed":
                await self._handle_census_change(intent.data)
                
            elif intent.type == "entry_event":
                await self._handle_entry_event(intent.data)
                
            elif intent.type == "periodic_reevaluate":
                await self._reevaluate_state()
        
        # Presence coordinator doesn't typically produce device actions
        # It updates house state which others react to
        return actions
    
    async def _reevaluate_state(self) -> None:
        """Re-evaluate house state from all inputs."""
        
        # Check for expired manual override
        if self._manual_override:
            if (self._manual_override.expires_at and 
                datetime.now() > self._manual_override.expires_at):
                self._manual_override = None
        
        # Build context
        ctx = await self._build_presence_context()
        
        # Infer state
        new_state, confidence = self._inference_engine.infer(ctx)
        
        # Attempt transition
        if self._state_machine.try_transition(new_state, confidence):
            # State changed - notify manager
            self.manager.update_house_state(new_state, confidence)
    
    async def _build_presence_context(self) -> PresenceContext:
        """Build context for state inference."""
        
        now = datetime.now()
        
        # Get Census data
        census = self._census_data or CensusData(
            total_occupants=0, 
            persons=[], 
            room_occupancy={}
        )
        
        # Calculate activity level
        if self._last_activity_time:
            idle_minutes = (now - self._last_activity_time).total_seconds() / 60
            self._activity_level = max(0.0, 1.0 - (idle_minutes / 60))
        
        return PresenceContext(
            total_occupants=census.total_occupants,
            known_persons=[p.person_id for p in census.persons if p.is_known],
            unknown_persons_detected=any(not p.is_known for p in census.persons),
            
            recent_entry=bool(
                self._last_entry_event and 
                (now - self._last_entry_event) < timedelta(minutes=15)
            ),
            recent_exit=False,  # TODO: Track exits
            was_empty_before_entry=self._was_empty_before_entry,
            last_motion_timestamp=self._last_activity_time,
            
            current_time=now,
            is_weekday=now.weekday() < 5,
            
            activity_level=self._activity_level,
            low_activity_duration=now - self._last_activity_time,
            
            sleep_start_time=time(22, 0),  # TODO: From config
            sleep_end_time=time(7, 0),
            
            current_state=self._state_machine.current_state,
            current_state_duration=self._state_machine.state_duration,
            
            geofence_approaching=await self._get_approaching_persons(),
            vacation_mode_manual=bool(
                self._manual_override and 
                self._manual_override.state == HouseState.VACATION
            ),
            guest_mode_manual=bool(
                self._manual_override and 
                self._manual_override.state == HouseState.GUEST
            ),
            
            safety_alert_active=await self._check_safety_alert(),
            security_alert_active=await self._check_security_alert(),
        )
    
    async def _handle_census_change(self, data: dict) -> None:
        """Handle Census update."""
        old_count = self._census_data.total_occupants if self._census_data else 0
        
        self._census_data = CensusData(
            total_occupants=data.get("total_occupants", 0),
            persons=[
                PersonLocation(**p) for p in data.get("persons", [])
            ],
            room_occupancy=data.get("room_occupancy", {}),
        )
        self._last_census_update = datetime.now()
        
        # Track empty→occupied transition
        if old_count == 0 and self._census_data.total_occupants > 0:
            self._was_empty_before_entry = True
        elif self._census_data.total_occupants > 0:
            self._was_empty_before_entry = False
        
        # Update activity
        self._last_activity_time = datetime.now()
        
        # Re-evaluate
        await self._reevaluate_state()
    
    async def _handle_entry_event(self, data: dict) -> None:
        """Handle door/entry sensor event."""
        self._last_entry_event = datetime.now()
        
        # Check if house was empty
        if self._census_data and self._census_data.total_occupants == 0:
            self._was_empty_before_entry = True
        
        self._last_activity_time = datetime.now()
        
        # Re-evaluate
        await self._reevaluate_state()
```

---

## 10. SENSORS & SERVICES

### Sensors

| Entity ID | Type | Purpose |
|-----------|------|---------|
| `sensor.ura_house_state` | sensor | Current state + attributes |
| `sensor.ura_house_state_confidence` | sensor | Confidence percentage |
| `binary_sensor.ura_house_occupied` | binary_sensor | Anyone home? |
| `binary_sensor.ura_house_sleeping` | binary_sensor | House in sleep state? |
| `binary_sensor.ura_guest_mode` | binary_sensor | Guest mode active? |

### Services

| Service | Parameters | Description |
|---------|------------|-------------|
| `ura.set_house_state` | state, duration_hours | Manual override |
| `ura.clear_house_state_override` | none | Return to auto |
| `ura.announce_guest` | name, duration_hours | Temporary guest |

---

## 11. DIAGNOSTICS

### Diagnostic Sensor

```yaml
sensor.ura_presence_diagnostics:
  state: "healthy"
  attributes:
    inference_count_today: 288
    state_transitions_today: 8
    manual_overrides_today: 1
    confidence_avg_24h: 0.85
    census_updates_24h: 1547
    inference_accuracy: 0.92  # Based on manual corrections
    
    # Current inference breakdown
    last_inference:
      timestamp: "2026-01-24T19:30:00"
      result: "HOME_EVENING"
      confidence: 0.88
      factors:
        occupancy: "2 known persons"
        time: "evening hours"
        activity: "normal"
        pattern_match: "typical Friday evening"
```

### Learning & Adaptation

```python
# Track patterns for improved inference
@dataclass
class PresencePattern:
    """Historical pattern for learning."""
    day_of_week: int
    hour: int
    typical_state: HouseState
    confidence: float
    sample_count: int


class PresencePatternLearner:
    """Learn household patterns over time."""
    
    async def record_observation(
        self,
        state: HouseState,
        timestamp: datetime,
        was_correct: bool,  # From user feedback
    ) -> None:
        """Record state observation for learning."""
        pass
    
    def get_expected_state(
        self,
        day_of_week: int,
        hour: int,
    ) -> tuple[HouseState, float] | None:
        """Get expected state based on historical patterns."""
        pass
```

---

## KEY DESIGN QUESTIONS

### Q1: Sleep Detection Accuracy

**Question:** How do we reliably detect SLEEP state without dedicated sleep sensors?

**Current Approach:**
- Time in sleep hours + low activity for 30+ minutes
- All persons in bedroom areas (from Census)

**Alternatives to Consider:**
- Phone charging status (HA companion app)
- Smart mattress/sleep tracker integration
- Light state in bedrooms
- Explicit "goodnight" routine trigger

**Recommendation Needed:** What signals are available for sleep detection?

---

### Q2: Guest Detection Strategy

**Question:** How should unknown persons be handled?

**Options:**
1. **Conservative:** Any unknown person → GUEST mode immediately
2. **Moderate:** Unknown + manual confirmation → GUEST mode
3. **Liberal:** Only manual "We have guests" → GUEST mode

**Implications:**
- Conservative: May false-positive on Census glitches
- Liberal: May miss guests and apply personalized settings inappropriately

**Recommendation Needed:** What's the preferred guest detection policy?

---

### Q3: Geofence Integration

**Question:** How should approaching-home geofence triggers work?

**Current Design:**
- Device tracker in "Home" zone → already home
- Device tracker approaching (near home zone?) → ARRIVING state

**Questions:**
- What geofence radius for "approaching"?
- Should ARRIVING pre-condition the house? (Lights, HVAC, etc.)
- Multiple family members - wait for all or first?

**Recommendation Needed:** Geofence behavior preferences?

---

**Document Status:** Design Complete - Pending Answers to Key Questions  
**Dependencies:** Census (URA 3.5), Entry Sensors, Geofencing  
**Consumers:** All other coordinators

---

## House Census & Guest Determination

*Added by cycle `census_ble_cancel_unrecognized` (2026-07-13). If you are re-investigating a "phantom guest" complaint, **start here**.*

### 1. Why there are two census paths

The house census answers a deceptively simple question: **how many people are inside the house, and how many of them are strangers?** Its output (the `unidentified_count`) is the primary signal that arms the *guest gate* in `presence.py` — which in turn drives HouseState (`OCCUPIED`, `GUEST`, `AWAY`), NM guest-arrival announcements, HVAC preset selection, and anomaly emissions on census transitions.

Historically, URA has had TWO computation paths in `custom_components/universal_room_automation/camera_census.py`:

- **Raw path** — `_cross_correlate_persons` (line ~1213). The original path. Computes:
  ```
  unidentified = max(0, camera_total - |face_recognized ∪ ble_home|)
  ```
  This *implicitly* cancels residents whom BLE places at home even if their face wasn't matched in this frame. Simple, correct in aggregate, but not area-aware — a resident in the kitchen cancels a camera hit in the foyer.

- **Enhanced path** — `_apply_enhanced_house_census` (line ~1956), default ON since v3.10.1. Computes `camera_unrecognized` per Frigate camera by asking the camera's own `sensor.*_last_recognized_face` whether a fresh (≤30 min) recognition matched a known resident. Then feeds a hold/decay stabilizer and returns `unidentified_count`.

The enhanced path was a signal-quality upgrade (per-camera face freshness). But **it never consulted BLE**. A resident whose face wasn't recently matched — even one whose phone was actively tracked to the SAME room as the camera — was invisible. In the field this manifested as the guest gate arming 2-4x/day with zero real guests present (observed on 2026-07-12; interior cams involved: playroom x2, master_hallway, staircase, foyer_fisheye, family_room).

The enhanced path had lost a property the raw path had. This cycle restores it *precisely* — per-area — rather than globally, so a resident in the kitchen does not cancel a genuine guest in the foyer.

### 2. Current arithmetic (per-camera, per-area)

Let, for interior camera `C` on this census cycle:
- `pc` = person_count reported by `sensor.<C>_person_count`
- `fresh_face` = 1 if `sensor.<C>_last_recognized_face` has a valid recent (`<= CENSUS_FACE_RECOGNITION_WINDOW_SECONDS`) match, else 0

The BLE-cancel step is **per-area, not per-camera**. Two cameras that cover the same physical area (e.g. playroom_a and playroom_b both in area `a_playroom`) are collapsed to a single per-area contribution BEFORE BLE subtraction, so that a resident BLE-there cannot leak past camera A into camera B.

Contribution formula (implemented in `_get_unrecognized_camera_count`, review fix-up 2026-07-13):
```
# Step 1: per-camera raw contribution, area-tagged
for each Frigate interior camera C:
    face_covered      = 1 if fresh_face(C) else 0
    raw_contribution  = max(0, pc(C) - face_covered)
    raw_contributions.append((C.area_id, raw_contribution))

# Step 2: collapse per-area (max within area; null-area kept individually)
area_raw_max = {aid: max(raw for (a, raw) in raw_contributions if a == aid) for aid in areas}

# Step 3: subtract BLE per-area
for aid, raw_max in area_raw_max.items():
    ble_here    = number of ACTIVE-tracking residents whose location resolves to aid
    correction  = min(raw_max, ble_here)
    final       = raw_max - correction

# Step 4: sum area finals + null-area (unassigned) contributions
```

The `raw_max`/`sum` collapse in Step 2 mirrors `_dedup_by_area` (same-area max, cross-area sum). The BLE subtraction lives OUTSIDE that helper (Step 3) because the per-area max must be known BEFORE `min(raw_max, ble_here)` can be computed correctly — moving the subtraction back into the per-camera loop reintroduces the same-area under-cancel bug (review fix-up M6 anchor).

**Resolving the room→area_id join** — `ble_here` for area `aid` counts each resident whose `person_coordinator.data[person]["location"]` (a room name string such as `"Kitchen"`) is registered as a URA room with `CONF_AREA_ID == aid`. The join is built by `_build_room_to_area_id_map`, which reads `CONF_AREA_ID` from each URA room config entry **directly** — NOT by inverting `person_coordinator._area_id_to_room`. The latter dict stores THREE keys per area (registry area_id, area display Name, normalized name) all mapping to the same room_name value; inverting it is last-wins over those three keys and typically yields the normalized name rather than the registry area_id. Since `CameraInfo.area_id` is the registry area_id, an inverted-dict helper silently never cancels when the area's display Name differs from its slug (the rename case).

#### Multi-person truth table

| pc | fresh_face | ble_here | raw_contrib | correction | final_contrib | Interpretation |
|---:|:-:|:-:|:-:|:-:|:-:|---|
| 1 | 0 | 1 | 1 | 1 | **0** | Resident alone, face missed — was FP, now cancelled |
| 1 | 1 | 1 | 0 | 0 | 0 | Resident, face matched — unchanged |
| 2 | 0 | 1 | 2 | 1 | **1** | Resident + guest, no faces — guest counted (I1 holds) |
| 2 | 1 | 1 | 1 | 1 | **0** | Double-cover — see known limitation below |
| 2 | 0 | 2 | 2 | 2 | 0 | Two residents in room, neither face-matched |
| 3 | 0 | 1 | 3 | 1 | **2** | 1 resident + 2 guests — both guests counted |
| 1 | 0 | 0 | 1 | 0 | 1 | Pure guest / no BLE resident in area — DETECTED (I1) |
| 0 | 0 | any | 0 | 0 | 0 | No detection, no contribution |

#### Hard invariants (see `PLANNING_census_ble_cancel_unrecognized.md` Section 3)

- **I1 — soundness:** a camera-detected person with NO resident BLE correlate in the SAME area still contributes to `unidentified_raw`. A resident in the kitchen NEVER cancels a guest in the foyer. Row 7 above is the load-bearing case.
- **I2 — completeness:** when at least one resident is BLE-here-in-area, contribution is reduced by exactly `min(raw_contribution, ble_here)`.
- **I3 — arithmetic bound:** the correction is monotone-reducing — it can only lower `unidentified_raw`, never raise it. On any exception in the helper, `{}` is returned and no cancellation is applied — the code degrades to the pre-cycle over-arming behavior rather than silently under-detecting guests.

**Who is excluded from `_ble_home_by_area`** (i.e. cannot cancel):

- `location ∈ {away, unknown, home, lost}` — the "not resolved to a specific room" sentinels.
- `tracking_status ∈ {stale, lost}` — bermuda_decay keeps a departed resident's `location` populated for up to 300s in STALE; a departed resident MUST NOT cancel a real guest arriving in the area they just left. Only `TRACKING_STATUS_ACTIVE` residents can cancel.
- Room names that do NOT resolve to any registered URA room's `CONF_AREA_ID` — these are DROPPED entirely (not bucketed under `None`). Bucketing under `None` would cross-cancel with null-area cameras (`CameraInfo.area_id is None`) and suppress real guests on unassigned-area cameras.

**Accepted sibling of row 4 (residual, not fixed this cycle):** if a resident's phone is FRESH but the resident is actually elsewhere unmapped (e.g. their location resolves to a room without a camera), and a genuine guest walks under that room's *area-siblings* — the `ble_here` count is correctly zero for the guest's area and I1 holds. The narrower case where a fresh-BLE resident is misplaced BY BLE to the guest's area (rather than their true area) reduces to a bad BLE reading and is not addressable at the census layer. Documented as a known limitation of the room→area join fidelity.

### 3. Interaction with the house-STATE AWAY paths

**Updated 2026-08-17 (audit `AUDIT_zone_away_house_vs_hvac.md`).** The prior text
here documented only the v4.7.14 predicate (`all tracked persons away AND
unidentified_count == 0`). The current `StateInferenceEngine.infer()`
(`presence.py:981-1208`) has **three** away decision points, and this cycle's
BLE-cancel correction feeds all of them by keeping `unidentified_count` honest.

1. **Base "nobody home"** — `presence.py:1059-1063`: `census_count == 0 AND not
   any_zone_occupied` → AWAY (conf 0.9). Here **room sensors are a HARD gate** —
   any occupied zone (via `any_zone_occupied`, itself the OR of `ZonePresenceTracker`
   modes over BLE/room-sensor/camera tiers) blocks base away, as does a non-zero census.

2. **Path α — phones confidently away (ACTIVE veto)** — `presence.py:1091-1101`:
   fires when `all_tracked_persons_away AND unidentified_count == 0 AND
   face_recognized_count == 0` → AWAY (conf 0.95). Path α does **NOT** reference
   `any_zone_occupied`, so it **ignores room sensors** — a stuck mmWave does not
   block it. The only things that keep the house home on this path are a
   camera-confirmed **person**: an unidentified body (`unidentified_count > 0`) or a
   face-recognized resident (`face_recognized_count > 0`). Camera **motion alone**
   (Tier-2 ghost) does not block it. The `face_recognized_count == 0` clause is the
   v5.78.0 D8 addition (commit `2e76a5a91`), replacing the earlier
   `census_count == 0` gate: a forgotten-phone resident's stale BLE fix used to keep
   `census_count >= 1` and wrongly block the veto (the census-hole fix).

3. **Path β — a phone is LOST/uncertain (LOST-admitted veto)** —
   `presence.py:1168-1208`: admits LOST-but-away trackers into the away
   denominator, and requires `all_trusted_or_lost_away_persons_away AND
   unidentified_count == 0 AND census_count == 0 AND not indoor_blocked` plus a
   grace clock (`grace_elapsed_for_lost_away` / `CONF_LOST_AWAY_GRACE_MIN`), a
   `sustained_external_empty` immediate-engage limb, and a sleep exemption. Because
   it gates on `not indoor_blocked` (the outdoor-excluded `any_indoor_zone_occupied`,
   `presence.py:1135-1139`), path β **DOES respect room sensors** — a real indoor
   occupancy blocks it. This is the conservative path.

**The two phone paths are ASYMMETRIC on room sensors — do not summarise them as
one rule.** Path α ignores room sensors (only a camera-confirmed person blocks it);
path β respects them. Precisely: when phones are confidently away, PHONE overrides
both room sensors and camera motion-ghosts (path α); when a phone is uncertain,
room-sensor occupancy keeps the house home (path β); base away respects both census
and zone occupancy.

**Six-state LOST evidence matrix (v5.78.0 PATH-ALPHA).** A phone tracker's raw
`not_home` / `home` / `unavailable` state is classified into a `tracking_status`
(e.g. `ACTIVE`, `STALE`, `LOST`) with a `tracking_reason`, and that classification
determines the tracker's **away-vote**: only ACTIVE-away trackers feed
`all_tracked_persons_away` (path α), while LOST-but-away trackers are admitted only
into the relaxed `all_trusted_or_lost_away_persons_away` denominator (path β) behind
the grace clock. bermuda_decay keeps a departed resident's `location` populated
during STALE (~300s), which is why STALE/LOST residents are excluded from BLE
cancellation (§ above) and from the ACTIVE away-vote. The matrix is what makes path
α (immediate, high-trust) and path β (graced, LOST-admitted) legitimately different
inputs rather than one predicate.

### 4. Where the guest gate consumes this

- Guest-gate arming: `custom_components/universal_room_automation/domain_coordinators/presence.py::_guest_gate_armed`.
- AWAY veto predicates (read `unidentified_count == 0`): base `presence.py:1059`, path α `presence.py:1091-1101`, path β `presence.py:1168-1208`.
- HouseState transitions consume `presence._guest_gate_armed`; downstream: HVAC preset, NM announces, anomaly emitter.

### 5. Known limitation — row 4 double-cover

If a camera sees `pc=2`, with a fresh face match for a resident AND that same resident is also BLE-located in the camera's area, the "face covers 1" heuristic AND the BLE cancellation both fire — cancelling two contributions for what is likely the same person. If the second person visible in the frame is a genuine guest, this cycle will miss them at that camera on that cycle.

Real-world frequency is low (all three conditions must coincide: fresh face AND BLE-here AND a co-present guest). Other guest-gate signals (WiFi VLAN diagnostic, cross-camera aggregation, sustained peak-hold) bound the miss window. The operator-resolved decision (2026-07-13) is: **accept as a known limitation; document; revisit if L2/L3 live data shows it manifesting**. A follow-up cycle would sharpen the formula to something like `covered = max(face_covered, ble_here)` on a "same person likely" heuristic — deferred.

### 6. Diagnostic surface

- `sensor.ura_camera_census_house` attribute `ble_cancelled_count` — number of contributions cancelled by BLE correlation on the most recent census cycle. Watch this attribute to observe the fix in action: it should increment as a resident walks under a camera, return to 0 after they leave the area or their face is matched.
- Existing attributes `camera_unrecognized`, `area_contributions`, `raw_pre_dedup_sum` remain unchanged in shape.


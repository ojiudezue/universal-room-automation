# PRESENCE COORDINATOR DESIGN

**Version:** 1.0  
**Status:** Design Complete  
**Last Updated:** 2026-01-24  
**Scope:** House-level state inference and management

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

```python
@dataclass
class PresenceContext:
    """All inputs for state inference."""
    
    # From Census
    total_occupants: int
    known_persons: list[str]
    unknown_persons_detected: bool
    
    # Recent events
    recent_entry: bool                    # Entry in last 15 min
    recent_exit: bool                     # Exit in last 15 min
    was_empty_before_entry: bool          # House was empty before this entry
    last_motion_timestamp: datetime | None
    
    # Time context
    current_time: datetime
    is_weekday: bool
    
    # Activity inference
    activity_level: float                 # 0.0-1.0 based on motion/events
    low_activity_duration: timedelta      # How long since significant activity
    
    # Configuration
    sleep_start_time: time                # e.g., 22:00
    sleep_end_time: time                  # e.g., 07:00
    
    # Current state
    current_state: HouseState
    current_state_duration: timedelta
    
    # External
    geofence_approaching: list[str]       # Persons approaching home
    vacation_mode_manual: bool            # Manually set vacation
    guest_mode_manual: bool               # Manually set guest mode
    
    # Safety/Security
    safety_alert_active: bool
    security_alert_active: bool


class StateInferenceEngine:
    """Infer house state from context."""
    
    def infer(self, ctx: PresenceContext) -> tuple[HouseState, float]:
        """
        Infer current house state.
        
        Returns:
            tuple of (state, confidence)
        """
        
        # Priority 1: Emergency overrides everything
        if ctx.safety_alert_active or ctx.security_alert_active:
            return HouseState.EMERGENCY, 0.99
        
        # Priority 2: Manual overrides
        if ctx.vacation_mode_manual:
            return HouseState.VACATION, 0.99
        
        if ctx.guest_mode_manual:
            return HouseState.GUEST, 0.95
        
        # Priority 3: Occupancy-based inference
        if ctx.total_occupants == 0:
            return self._infer_empty_house(ctx)
        else:
            return self._infer_occupied_house(ctx)
    
    def _infer_empty_house(
        self, 
        ctx: PresenceContext
    ) -> tuple[HouseState, float]:
        """Infer state when house is empty."""
        
        # Someone approaching?
        if ctx.geofence_approaching:
            return HouseState.ARRIVING, 0.85
        
        # Long empty = vacation candidate
        if ctx.current_state == HouseState.AWAY:
            if ctx.current_state_duration > timedelta(days=2):
                return HouseState.VACATION, 0.70
        
        return HouseState.AWAY, 0.90
    
    def _infer_occupied_house(
        self, 
        ctx: PresenceContext
    ) -> tuple[HouseState, float]:
        """Infer state when house is occupied."""
        
        # Recent arrival from empty?
        if ctx.recent_entry and ctx.was_empty_before_entry:
            # Still in arriving transition
            if ctx.current_state_duration < timedelta(minutes=15):
                return HouseState.ARRIVING, 0.85
        
        # Unknown persons = potential guest
        if ctx.unknown_persons_detected:
            return HouseState.GUEST, 0.75
        
        # Time-based inference
        hour = ctx.current_time.hour
        
        # Sleep inference
        if self._is_sleep_hours(ctx):
            if ctx.low_activity_duration > timedelta(minutes=30):
                return HouseState.SLEEP, 0.85
            else:
                return HouseState.HOME_NIGHT, 0.70
        
        # Waking inference
        if self._is_waking_hours(ctx):
            if ctx.activity_level > 0.3:
                return HouseState.WAKING, 0.80
            else:
                return HouseState.SLEEP, 0.75
        
        # Day/Evening/Night based on time
        if 6 <= hour < 17:
            return HouseState.HOME_DAY, 0.80
        elif 17 <= hour < 21:
            return HouseState.HOME_EVENING, 0.80
        elif 21 <= hour < 24:
            return HouseState.HOME_NIGHT, 0.75
        else:
            # Early morning (0-6)
            if ctx.activity_level > 0.3:
                return HouseState.WAKING, 0.70
            else:
                return HouseState.SLEEP, 0.80
    
    def _is_sleep_hours(self, ctx: PresenceContext) -> bool:
        """Check if current time is in sleep hours."""
        current = ctx.current_time.time()
        
        # Handle overnight wrap (e.g., 22:00 to 07:00)
        if ctx.sleep_start_time > ctx.sleep_end_time:
            return current >= ctx.sleep_start_time or current < ctx.sleep_end_time
        else:
            return ctx.sleep_start_time <= current < ctx.sleep_end_time
    
    def _is_waking_hours(self, ctx: PresenceContext) -> bool:
        """Check if current time is in waking window."""
        current = ctx.current_time.time()
        wake_end = (
            datetime.combine(date.today(), ctx.sleep_end_time) 
            + timedelta(hours=1)
        ).time()
        
        return ctx.sleep_end_time <= current < wake_end
```

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

# SECURITY COORDINATOR DESIGN

**Version:** 1.0  
**Status:** Design Complete  
**Last Updated:** 2026-01-24  
**Scope:** Intrusion detection, access control, anomaly monitoring

---

## TABLE OF CONTENTS

1. [Overview](#1-overview)
2. [Armed States](#2-armed-states)
3. [Entry Point Monitoring](#3-entry-point-monitoring)
4. [Sanctioned vs Unsanctioned Entry](#4-sanctioned-vs-unsanctioned-entry)
5. [Anomaly Detection](#5-anomaly-detection)
6. [Response Actions](#6-response-actions)
7. [Notification Strategy](#7-notification-strategy)
8. [House State Integration](#8-house-state-integration)
9. [Implementation](#9-implementation)
10. [Sensors & Entities](#10-sensors--entities)
11. [Diagnostics](#11-diagnostics)

---

## 1. OVERVIEW

### Purpose

The Security Coordinator **detects and responds to anomalous human activity**:
- Unauthorized entry
- Unexpected presence
- Suspicious patterns
- Access control

### Design Principles

| Principle | Description |
|-----------|-------------|
| **Know Who's Home** | Leverages Census for occupancy awareness |
| **Sanctioned Entry** | Distinguishes expected from unexpected |
| **Graduated Response** | Response matches threat level |
| **Multi-Signal** | Combines sensors, cameras, patterns |
| **No False Comfort** | Better to alert than miss |

### What Security Monitors

```
SECURITY COORDINATOR SCOPE
├── Entry Points
│   ├── Doors (front, back, garage)
│   ├── Windows (if monitored)
│   └── Garage doors
│
├── Motion Detection
│   ├── Interior motion sensors
│   ├── Exterior motion sensors
│   └── Camera person detection (Frigate)
│
├── Presence Awareness
│   ├── Census (who's in which room)
│   ├── Known vs unknown persons
│   └── Expected arrivals (geofence)
│
└── Patterns
    ├── Normal entry times
    ├── Expected behaviors
    └── Anomaly detection
```

### What Security Does NOT Monitor

| Not This | That's This |
|----------|-------------|
| Environmental hazards | Safety Coordinator |
| House state inference | Presence Coordinator |
| Comfort settings | Comfort Coordinator |

---

## 2. ARMED STATES

### State Definitions

```python
class ArmedState(Enum):
    """Security armed states."""
    
    DISARMED = "disarmed"
    # No monitoring active
    # Used when: Family home and awake
    # Monitors: Nothing actively
    
    HOME = "home"
    # Perimeter monitoring only
    # Used when: Family home, sleeping or evening
    # Monitors: Entry points (doors, windows, garage)
    # Ignores: Interior motion
    
    AWAY = "away"
    # Full monitoring
    # Used when: Nobody home
    # Monitors: All entry points + interior motion
    
    VACATION = "vacation"
    # Enhanced monitoring
    # Used when: Extended away
    # Monitors: Everything + extra logging + patterns
```

### State Transition Rules

```python
# Armed state follows House State but can be manually overridden

HOUSE_STATE_TO_ARMED = {
    HouseState.AWAY: ArmedState.AWAY,
    HouseState.ARRIVING: ArmedState.DISARMED,  # Disarm for arrival
    HouseState.HOME_DAY: ArmedState.DISARMED,
    HouseState.HOME_EVENING: ArmedState.HOME,   # Perimeter only
    HouseState.HOME_NIGHT: ArmedState.HOME,
    HouseState.SLEEP: ArmedState.HOME,          # Full home arm
    HouseState.WAKING: ArmedState.DISARMED,
    HouseState.GUEST: ArmedState.HOME,          # Modified - guest areas OK
    HouseState.VACATION: ArmedState.VACATION,
    HouseState.EMERGENCY: ArmedState.DISARMED,  # Safety takes over
}
```

---

## 3. ENTRY POINT MONITORING

### Entry Point Types

```python
@dataclass
class EntryPoint:
    """Monitored entry point."""
    
    entity_id: str
    name: str
    type: str              # "door", "window", "garage"
    location: str          # "front", "back", "garage", "side"
    is_perimeter: bool     # True = monitored in HOME mode
    is_primary: bool       # True = normal entry point


# Example configuration
ENTRY_POINTS = [
    EntryPoint("binary_sensor.front_door", "Front Door", "door", "front", True, True),
    EntryPoint("binary_sensor.back_door", "Back Door", "door", "back", True, True),
    EntryPoint("binary_sensor.garage_entry", "Garage Entry", "door", "garage", True, True),
    EntryPoint("cover.garage_door", "Garage Door", "garage", "garage", True, True),
    EntryPoint("binary_sensor.master_window", "Master Window", "window", "side", True, False),
    # etc.
]
```

### Entry Event Processing

```python
@dataclass
class EntryEvent:
    """Detected entry event."""
    
    timestamp: datetime
    entry_point: EntryPoint
    event_type: str         # "opened", "closed", "unlocked"
    person_detected: bool   # Camera/motion confirmed
    person_id: str | None   # If identified by Census
    
    
class EntryProcessor:
    """Process entry events and determine response."""
    
    async def process(
        self, 
        event: EntryEvent, 
        armed_state: ArmedState,
        census: CensusData,
    ) -> SecurityVerdict:
        
        # DISARMED: Log only
        if armed_state == ArmedState.DISARMED:
            return SecurityVerdict.LOG_ONLY
        
        # Check if entry is sanctioned
        verdict = await self._evaluate_entry(event, armed_state, census)
        
        return verdict
    
    async def _evaluate_entry(
        self,
        event: EntryEvent,
        armed_state: ArmedState,
        census: CensusData,
    ) -> SecurityVerdict:
        
        # HOME mode: Only perimeter matters
        if armed_state == ArmedState.HOME:
            if not event.entry_point.is_perimeter:
                return SecurityVerdict.LOG_ONLY
        
        # Check if person is known
        if event.person_id and event.person_id in census.known_persons:
            return SecurityVerdict.SANCTIONED
        
        # Check expected arrivals (geofence approaching)
        if event.person_id in self._expected_arrivals:
            return SecurityVerdict.SANCTIONED
        
        # Unknown entry while armed
        if armed_state == ArmedState.AWAY:
            return SecurityVerdict.ALERT
        
        if armed_state == ArmedState.VACATION:
            return SecurityVerdict.ALERT_HIGH
        
        # HOME mode perimeter breach
        if armed_state == ArmedState.HOME:
            return SecurityVerdict.INVESTIGATE
        
        return SecurityVerdict.LOG_ONLY
```

---

## 4. SANCTIONED VS UNSANCTIONED ENTRY

### Core Concept

```
SANCTIONED ENTRY
├── Known person (in Census) arrives
├── Expected arrival (geofence approaching)
├── Scheduled entry (cleaning service, etc.)
└── Manual authorization ("Guest arriving")

UNSANCTIONED ENTRY
├── Unknown person detected
├── Entry while nobody expected
├── Entry through unusual point
└── Entry at unusual time
```

### Verdict Types

```python
class SecurityVerdict(Enum):
    """Result of entry evaluation."""
    
    SANCTIONED = "sanctioned"
    # Entry is expected and authorized
    # Action: Log, no alert
    
    LOG_ONLY = "log_only"
    # Entry recorded but not evaluated (disarmed)
    # Action: Log only
    
    INVESTIGATE = "investigate"
    # Unusual but not clearly threatening
    # Action: Log, minor alert, watch for follow-up
    
    NOTIFY = "notify"
    # Unexpected but known person
    # Action: Notify owner, don't alarm
    
    ALERT = "alert"
    # Unsanctioned entry, potential intrusion
    # Action: Full alert, security lighting
    
    ALERT_HIGH = "alert_high"
    # High-confidence intrusion (vacation mode)
    # Action: Maximum response
```

### Sanctioning Logic

```python
class SanctionChecker:
    """Determine if entry is sanctioned."""
    
    def __init__(self):
        self._expected_arrivals: set[str] = set()
        self._scheduled_entries: list[ScheduledEntry] = []
        self._temporary_guests: dict[str, datetime] = {}
    
    def is_sanctioned(
        self,
        person_id: str | None,
        entry_point: EntryPoint,
        timestamp: datetime,
        census: CensusData,
    ) -> tuple[bool, str]:
        """
        Check if entry is sanctioned.
        
        Returns: (is_sanctioned, reason)
        """
        
        # Known family member
        if person_id in census.known_persons:
            return True, f"Known person: {person_id}"
        
        # Expected arrival (approaching via geofence)
        if person_id in self._expected_arrivals:
            return True, f"Expected arrival: {person_id}"
        
        # Temporary guest
        if person_id in self._temporary_guests:
            if datetime.now() < self._temporary_guests[person_id]:
                return True, f"Authorized guest: {person_id}"
        
        # Scheduled entry
        for entry in self._scheduled_entries:
            if entry.matches(entry_point, timestamp):
                return True, f"Scheduled: {entry.description}"
        
        # Not sanctioned
        return False, "Unknown/unexpected entry"
    
    def add_expected_arrival(self, person_id: str) -> None:
        """Add expected arrival (from geofence)."""
        self._expected_arrivals.add(person_id)
    
    def add_temporary_guest(
        self, 
        person_id: str, 
        until: datetime
    ) -> None:
        """Authorize temporary guest."""
        self._temporary_guests[person_id] = until
```

---

## 5. ANOMALY DETECTION

### Anomaly Types

```python
class AnomalyType(Enum):
    """Types of security anomalies."""
    
    UNUSUAL_TIME = "unusual_time"
    # Entry at unexpected time (3am when usually 6pm)
    
    UNUSUAL_POINT = "unusual_point"
    # Entry through window instead of door
    
    MOTION_NO_ENTRY = "motion_no_entry"
    # Interior motion without entry event
    
    CAMERA_UNKNOWN = "camera_unknown"
    # Camera sees person, Census doesn't recognize
    
    MULTIPLE_FAILURES = "multiple_failures"
    # Multiple lock/entry attempts
    
    PATTERN_BREAK = "pattern_break"
    # Behavior doesn't match normal patterns
```

### Pattern Learning

```python
class SecurityPatternLearner:
    """Learn normal patterns to detect anomalies."""
    
    def __init__(self):
        self._entry_patterns: dict[str, list[int]] = {}  # person -> [hours]
        self._entry_point_patterns: dict[str, Counter] = {}
    
    def record_entry(
        self,
        person_id: str,
        entry_point: str,
        timestamp: datetime,
    ) -> None:
        """Record entry for pattern learning."""
        
        # Track typical entry hours
        if person_id not in self._entry_patterns:
            self._entry_patterns[person_id] = []
        self._entry_patterns[person_id].append(timestamp.hour)
        
        # Track typical entry points
        if person_id not in self._entry_point_patterns:
            self._entry_point_patterns[person_id] = Counter()
        self._entry_point_patterns[person_id][entry_point] += 1
    
    def is_unusual_time(
        self, 
        person_id: str, 
        hour: int
    ) -> tuple[bool, float]:
        """Check if entry time is unusual for this person."""
        
        patterns = self._entry_patterns.get(person_id, [])
        if len(patterns) < 10:
            return False, 0.0  # Not enough data
        
        # Calculate how unusual this hour is
        hour_counts = Counter(patterns)
        total = sum(hour_counts.values())
        this_hour_freq = hour_counts.get(hour, 0) / total
        
        # Very unusual if < 5% of entries at this hour
        is_unusual = this_hour_freq < 0.05
        anomaly_score = 1.0 - this_hour_freq
        
        return is_unusual, anomaly_score
```

---

## 6. RESPONSE ACTIONS

### Response Matrix

| Verdict | Armed State | Actions |
|---------|-------------|---------|
| ALERT_HIGH | VACATION | All lights, all notifications, camera recording |
| ALERT | AWAY | Security lights, full notifications, camera recording |
| INVESTIGATE | HOME | Entry lights, notification to owner |
| NOTIFY | Any | Notification only |
| SANCTIONED | Any | Log only |

### Response Implementation

```python
class SecurityResponseGenerator:
    """Generate responses to security events."""
    
    async def generate(
        self,
        verdict: SecurityVerdict,
        event: EntryEvent,
        armed_state: ArmedState,
    ) -> SecurityResponse:
        
        actions = []
        notifications = []
        
        if verdict == SecurityVerdict.ALERT_HIGH:
            # Maximum response
            actions.extend([
                self._all_lights_on(),
                self._security_lights_flash(),
                self._camera_record(event.entry_point),
                self._lock_other_doors(),
            ])
            notifications.append(self._alert_notification(event, Severity.HIGH))
            
        elif verdict == SecurityVerdict.ALERT:
            # Standard intrusion response
            actions.extend([
                self._security_lights_on(event.entry_point),
                self._camera_record(event.entry_point),
            ])
            notifications.append(self._alert_notification(event, Severity.HIGH))
            
        elif verdict == SecurityVerdict.INVESTIGATE:
            # Minor response, investigate
            actions.append(self._entry_lights_on(event.entry_point))
            notifications.append(self._investigate_notification(event))
            
        elif verdict == SecurityVerdict.NOTIFY:
            # Just notify
            notifications.append(self._info_notification(event))
        
        return SecurityResponse(
            verdict=verdict,
            event=event,
            actions=actions,
            notifications=notifications,
        )
    
    def _security_lights_flash(self) -> CoordinatorAction:
        """Flash security lights red."""
        return NotificationAction(
            coordinator="security",
            action_type="security_lights",
            severity=Severity.HIGH,
            confidence=0.90,
            reason="Intruder alert - flashing lights",
            channels=["lights"],
            message="intruder",  # Light pattern name
        )
    
    def _camera_record(self, entry_point: EntryPoint) -> CoordinatorAction:
        """Trigger camera recording."""
        # Affordance for Frigate/UniFi Protect
        return ServiceCallAction(
            coordinator="security",
            action_type="camera_record",
            severity=Severity.HIGH,
            confidence=0.90,
            reason=f"Recording at {entry_point.name}",
            domain="camera",
            service="record",
            service_data={
                "entity_id": self._get_camera_for_entry(entry_point),
                "duration": 60,
            },
        )
```

---

## 7. NOTIFICATION STRATEGY

### Channel Selection

| Verdict | Channels | Repeat |
|---------|----------|--------|
| ALERT_HIGH | iMessage + Speaker + Lights | Every 30s until acknowledged |
| ALERT | iMessage + Speaker + Lights | Every 2min until acknowledged |
| INVESTIGATE | iMessage + Entry Light | Once |
| NOTIFY | iMessage | Once |

### Light Patterns for Security

```python
SECURITY_LIGHT_PATTERNS = {
    "intruder": {
        "color": (255, 0, 0),    # Red
        "effect": "flash",
        "interval_ms": 500,
        "duration_seconds": 60,
    },
    "armed": {
        "color": (255, 0, 0),
        "brightness": 50,
        "effect": "solid",
        "lights": ["light.entry_hall"],  # Entry lights only
    },
    "investigate": {
        "color": (255, 255, 0),  # Yellow
        "effect": "pulse",
        "duration_seconds": 30,
    },
}
```

---

## 8. HOUSE STATE INTEGRATION

### Automatic Armed State

```python
async def _on_house_state_changed(self, data: dict) -> None:
    """React to house state changes."""
    
    new_house_state = data["state"]
    recommended_armed = HOUSE_STATE_TO_ARMED.get(new_house_state)
    
    if recommended_armed and not self._manual_override:
        await self._set_armed_state(recommended_armed)
        
        _LOGGER.info(
            f"Armed state auto-changed to {recommended_armed.value} "
            f"(house state: {new_house_state.name})"
        )
```

### Entry Path Disarming

```python
async def _prepare_for_arrival(self, person_id: str) -> None:
    """Prepare for expected arrival."""
    
    # Add to expected arrivals
    self._sanction_checker.add_expected_arrival(person_id)
    
    # If AWAY, prepare to disarm entry path
    if self._armed_state == ArmedState.AWAY:
        # Don't fully disarm yet, but suppress alerts for this person
        self._arrival_pending = person_id
        
        _LOGGER.info(f"Preparing for arrival: {person_id}")
```

---

## 9. IMPLEMENTATION

```python
class SecurityCoordinator(BaseCoordinator):
    """Intrusion detection and access control."""
    
    COORDINATOR_ID = "security"
    PRIORITY = 80
    
    def __init__(self, hass: HomeAssistant, manager: CoordinatorManager):
        super().__init__(hass, manager)
        
        self._armed_state = ArmedState.DISARMED
        self._manual_override = False
        self._entry_processor = EntryProcessor()
        self._sanction_checker = SanctionChecker()
        self._pattern_learner = SecurityPatternLearner()
        self._response_generator = SecurityResponseGenerator()
    
    async def async_setup(self) -> None:
        """Setup security coordinator."""
        
        # Subscribe to house state changes
        async_dispatcher_connect(
            self.hass,
            SIGNAL_HOUSE_STATE_CHANGED,
            self._on_house_state_changed,
        )
        
        # Register entry point triggers
        for entry_point in ENTRY_POINTS:
            self.register_state_trigger(
                entity_id=entry_point.entity_id,
                intent_type="entry_event",
            )
        
        # Register motion sensor triggers
        for motion_sensor in self._motion_sensors:
            self.register_state_trigger(
                entity_id=motion_sensor,
                intent_type="motion_event",
                condition=lambda old, new: new.state == "on",
            )
    
    async def evaluate(
        self,
        intents: list[Intent],
        context: CoordinatorContext,
    ) -> list[CoordinatorAction]:
        
        actions = []
        
        for intent in intents:
            if intent.type == "entry_event":
                response = await self._handle_entry(intent, context)
                if response:
                    actions.extend(response.actions)
                    
            elif intent.type == "motion_event":
                response = await self._handle_motion(intent, context)
                if response:
                    actions.extend(response.actions)
                    
            elif intent.type == "house_state_changed":
                await self._on_house_state_changed(intent.data)
        
        return actions
    
    async def _handle_entry(
        self,
        intent: Intent,
        context: CoordinatorContext,
    ) -> SecurityResponse | None:
        
        entity_id = intent.data["entity_id"]
        new_state = intent.data["new_state"]
        
        # Find entry point
        entry_point = self._get_entry_point(entity_id)
        if not entry_point:
            return None
        
        # Only process "opened" events
        if new_state not in ("on", "open", "unlocked"):
            return None
        
        # Build entry event
        event = EntryEvent(
            timestamp=datetime.now(),
            entry_point=entry_point,
            event_type=new_state,
            person_detected=await self._check_camera_detection(entry_point),
            person_id=await self._identify_person(entry_point),
        )
        
        # Get census data
        census = context.census
        
        # Process entry
        verdict = await self._entry_processor.process(
            event, 
            self._armed_state,
            census,
        )
        
        # Record for pattern learning
        if event.person_id:
            self._pattern_learner.record_entry(
                event.person_id,
                entry_point.entity_id,
                event.timestamp,
            )
        
        # Generate response
        return await self._response_generator.generate(
            verdict,
            event,
            self._armed_state,
        )
    
    # Services
    async def async_arm(self, state: str) -> None:
        """Manually arm to specific state."""
        self._armed_state = ArmedState(state)
        self._manual_override = True
    
    async def async_disarm(self) -> None:
        """Disarm security."""
        self._armed_state = ArmedState.DISARMED
        self._manual_override = False
    
    async def async_authorize_guest(
        self, 
        name: str, 
        duration_hours: float
    ) -> None:
        """Authorize temporary guest."""
        until = datetime.now() + timedelta(hours=duration_hours)
        self._sanction_checker.add_temporary_guest(name, until)
```

---

## 10. SENSORS & ENTITIES

### Created Sensors

```yaml
sensor.ura_security_armed_state:
  state: "home"
  attributes:
    auto_set: true
    manual_override: false
    house_state: "HOME_EVENING"

binary_sensor.ura_security_alert:
  state: "off"
  device_class: safety
  attributes:
    alert_type: null
    location: null
    timestamp: null

sensor.ura_security_last_entry:
  state: "Front Door"
  attributes:
    timestamp: "2026-01-24T18:30:00"
    person: "oji"
    sanctioned: true
```

### Services

| Service | Parameters | Description |
|---------|------------|-------------|
| `ura.security_arm` | state | Set armed state |
| `ura.security_disarm` | none | Disarm |
| `ura.authorize_guest` | name, duration_hours | Temp guest |
| `ura.add_expected_arrival` | person_id | Expect arrival |

---

## 11. DIAGNOSTICS

```yaml
sensor.ura_security_diagnostics:
  state: "healthy"
  attributes:
    armed_state: "home"
    entry_points_monitored: 8
    motion_sensors_monitored: 6
    entries_today: 12
    alerts_today: 0
    false_positives_7d: 1
    pattern_data_entries: 1547
```

---

## KEY DESIGN QUESTIONS

### Q1: Camera Integration

**Question:** How should Frigate/UniFi Protect cameras integrate?

**Options:**
1. **Person detection** → Use camera person detection to confirm entry
2. **Recording** → Trigger recording on security events
3. **Identification** → Use facial recognition (privacy concerns)

**Current Design:** Affordance for detection + recording, not identification.

**Recommendation Needed:** Camera integration preferences?

---

### Q2: Lock Integration

**Question:** Do you have smart locks? How should they integrate?

**Options:**
1. **Auto-lock** → Lock doors on arming
2. **Alert on unlock** → Notify on unexpected unlocks
3. **Temporary codes** → Generate guest codes

**Recommendation Needed:** Smart lock integration?

---

### Q3: Geofence Radius

**Question:** What radius triggers "approaching home"?

**Options:**
- 500m: Very early warning
- 200m: Reasonable advance notice
- 100m: Just before arrival

**Recommendation Needed:** Preferred geofence radius for pre-arming?

---

**Document Status:** Design Complete - Pending Answers  
**Priority:** 80 (Second highest after Safety)  
**Dependencies:** Census, Entry Sensors, House State

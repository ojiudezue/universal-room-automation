# URA DOMAIN COORDINATOR ARCHITECTURE

**Version:** 1.0  
**Status:** Design Complete  
**Last Updated:** 2026-01-24  
**Scope:** Whole-house coordination across all URA domain coordinators

---

## TABLE OF CONTENTS

1. [Overview](#1-overview)
2. [Architecture Principles](#2-architecture-principles)
3. [Coordinator Hierarchy](#3-coordinator-hierarchy)
4. [Coordinator Manager](#4-coordinator-manager)
5. [Intent & Action Model](#5-intent--action-model)
6. [House State Framework](#6-house-state-framework)
7. [Conflict Resolution](#7-conflict-resolution)
8. [Communication Patterns](#8-communication-patterns)
9. [Shared Services](#9-shared-services)
10. [Persistence & Recovery](#10-persistence--recovery)
11. [Home Assistant Integration](#11-home-assistant-integration)
12. [Coordinator Summary](#12-coordinator-summary)

---

## 1. OVERVIEW

### Purpose

The URA Domain Coordinator Architecture provides a **centralized, priority-aware orchestration system** for managing whole-house automation across multiple domains (safety, security, energy, comfort, etc.).

### Design Goals

| Goal | Description |
|------|-------------|
| **Safety First** | Safety coordinator can override all others |
| **Predictable Ordering** | Guaranteed priority-based evaluation |
| **Conflict Resolution** | Central arbitration prevents race conditions |
| **HA Compatible** | Works within Home Assistant's single-threaded async model |
| **Recoverable** | State persists across restarts |
| **Observable** | Full audit trail of decisions and actions |

### What This Architecture Provides

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         COORDINATOR ARCHITECTURE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  TRIGGERS                    COORDINATOR MANAGER                             │
│  ┌──────────────┐           ┌──────────────────────────────────────────┐    │
│  │ state_changed│──────────▶│  Intent Queue                            │    │
│  │ time patterns│──────────▶│  ↓                                       │    │
│  │ census events│──────────▶│  Priority-Ordered Evaluation             │    │
│  │ manual input │──────────▶│  ↓                                       │    │
│  └──────────────┘           │  Conflict Resolution                     │    │
│                             │  ↓                                       │    │
│                             │  Action Execution                        │    │
│                             └──────────────────────────────────────────┘    │
│                                              │                               │
│                    ┌─────────────────────────┼─────────────────────────┐    │
│                    ▼                         ▼                         ▼    │
│              ┌──────────┐             ┌──────────┐             ┌──────────┐ │
│              │  Safety  │             │ Security │             │  Energy  │ │
│              │Coordinator│            │Coordinator│            │Coordinator││
│              └──────────┘             └──────────┘             └──────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. ARCHITECTURE PRINCIPLES

### 2.1 Tiered Execution (Not Peer Event Bus)

**Why not pure event bus?**
- HA doesn't guarantee event handler ordering
- Race conditions when multiple coordinators react to same trigger
- No built-in conflict resolution

**Our approach: Tiered Execution**
1. **Triggers** queue intents (don't act directly)
2. **Coordinator Manager** processes intents in priority order
3. **Conflict Resolver** approves/denies proposed actions
4. **Executor** runs approved actions

### 2.2 Intents vs Actions

| Concept | Description | Example |
|---------|-------------|---------|
| **Intent** | A request to evaluate a situation | "Water leak detected at sensor X" |
| **Action** | A proposed change to the system | "Turn off water valve, notify owner" |

Coordinators receive intents and propose actions. They don't execute directly.

### 2.3 Priority-Based Evaluation

Coordinators are **always** evaluated in this order:

```python
PRIORITY_ORDER = [
    "safety",      # 1. Life safety, environmental hazards
    "security",    # 2. Intrusion, access control
    "presence",    # 3. House state (informs others)
    "energy",      # 4. TOU optimization, load management
    "hvac",        # 5. Zone-level climate control
    "comfort",     # 6. Room-level comfort
]
```

Higher-priority coordinators can block or modify lower-priority actions.

### 2.4 Single Source of Truth

| Data | Owner | Consumers |
|------|-------|-----------|
| House State | Presence Coordinator | All coordinators |
| Person Locations | Census (URA 3.5) | All coordinators |
| Energy Constraints | Energy Coordinator | HVAC, Comfort |
| Armed State | Security Coordinator | Presence, Notifications |

---

## 3. COORDINATOR HIERARCHY

### Visual Hierarchy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         COORDINATOR HIERARCHY                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  FOUNDATION LAYER                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  CENSUS (URA 3.5)              PRESENCE COORDINATOR                  │    │
│  │  ════════════════              ════════════════════                  │    │
│  │  WHO is WHERE                  WHAT STATE is the HOUSE               │    │
│  │  • Person tracking             • State inference                     │    │
│  │  • Room transitions            • State machine                       │    │
│  │  • Occupancy counts            • Manual overrides                    │    │
│  │  DATA PROVIDER                 STATE PROVIDER                        │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  TIER 1: SAFETY (Priority 100) - Cannot be overridden                       │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  SAFETY COORDINATOR                                                  │    │
│  │  ══════════════════                                                  │    │
│  │  Environmental hazards that threaten life or property                │    │
│  │  • Fire/smoke         • Water leaks        • Freeze risk            │    │
│  │  • CO/CO2             • Air quality        • Extreme temps          │    │
│  │  OVERRIDES: All other coordinators                                  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  TIER 2: SECURITY (Priority 80)                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  SECURITY COORDINATOR                                                │    │
│  │  ════════════════════                                                │    │
│  │  Intrusion detection and access control                             │    │
│  │  • Entry monitoring   • Anomaly detection  • Armed states           │    │
│  │  • Sanctioned vs unsanctioned entry                                 │    │
│  │  OVERRIDES: Energy, HVAC, Comfort                                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  TIER 3: INFRASTRUCTURE (Priority 40)                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  ENERGY COORDINATOR                                                  │    │
│  │  ══════════════════                                                  │    │
│  │  Whole-house energy optimization                                    │    │
│  │  • TOU optimization   • Battery management  • Load prioritization   │    │
│  │  • Governs: HVAC (via constraints), Pool, EVSE                      │    │
│  │  SCOPE: House-level                                                 │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  TIER 4: DOMAIN CONTROL (Priority 30/20)                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  HVAC COORDINATOR (30)         COMFORT COORDINATOR (20)              │    │
│  │  ════════════════════          ════════════════════                  │    │
│  │  Zone-level climate            Room-level comfort                   │    │
│  │  • 3 Carrier zones             • Room fans, heaters                 │    │
│  │  • Responds to Energy          • Comfort lighting                   │    │
│  │  • Responds to Comfort         • Person preferences                 │    │
│  │  SCOPE: Zone (3 zones)         SCOPE: Room (20+ rooms)             │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  SHARED SERVICES                                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  NOTIFICATION MANAGER          CONFLICT RESOLVER                     │    │
│  │  ════════════════════          ═════════════════                     │    │
│  │  • iMessage                    • Priority arbitration               │    │
│  │  • Speakers (TTS)              • Severity weighting                 │    │
│  │  • Visual (lights)             • Confidence scoring                 │    │
│  │  • Quiet hours                 • Audit logging                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Priority Values

| Coordinator | Base Priority | Can Override |
|-------------|---------------|--------------|
| Safety | 100 | Everything |
| Security | 80 | Energy, HVAC, Comfort |
| Presence | 60 | (Informational only) |
| Energy | 40 | HVAC, Comfort |
| HVAC | 30 | Comfort |
| Comfort | 20 | Nothing |

---

## 4. COORDINATOR MANAGER

### Purpose

The **Coordinator Manager** is the central orchestrator that:
1. Receives intents from triggers
2. Invokes coordinators in priority order
3. Collects proposed actions
4. Resolves conflicts
5. Executes approved actions

### Implementation

```python
# domain_coordinators/coordinator_manager.py

class CoordinatorManager:
    """
    Central orchestrator for all domain coordinators.
    
    This is the ONLY component that executes actions.
    Coordinators propose; Manager disposes.
    """
    
    PRIORITY_ORDER = [
        "safety",
        "security", 
        "presence",
        "energy",
        "hvac",
        "comfort",
    ]
    
    def __init__(self, hass: HomeAssistant, db_path: str):
        self.hass = hass
        self._intent_queue: asyncio.Queue[Intent] = asyncio.Queue()
        self._coordinators: dict[str, BaseCoordinator] = {}
        self._conflict_resolver = ConflictResolver()
        self._notification_manager = NotificationManager(hass)
        self._decision_logger = DecisionLogger(db_path)
        self._compliance_tracker = ComplianceTracker(hass, db_path)
        
        # Current state
        self._house_state: HouseState = HouseState.AWAY
        self._house_state_confidence: float = 0.5
    
    async def async_setup(self) -> None:
        """Initialize all coordinators and start processing."""
        
        # Initialize coordinators
        self._coordinators = {
            "safety": SafetyCoordinator(self.hass, self),
            "security": SecurityCoordinator(self.hass, self),
            "presence": PresenceCoordinator(self.hass, self),
            "energy": EnergyCoordinator(self.hass, self),
            "hvac": HVACCoordinator(self.hass, self),
            "comfort": ComfortCoordinator(self.hass, self),
        }
        
        # Setup each coordinator (registers triggers)
        for name, coordinator in self._coordinators.items():
            _LOGGER.info(f"Setting up {name} coordinator")
            await coordinator.async_setup()
        
        # Start intent processing loop
        self._processing_task = asyncio.create_task(
            self._process_intents_loop()
        )
        
        _LOGGER.info("Coordinator Manager initialized")
    
    async def queue_intent(self, intent: Intent) -> None:
        """
        Queue an intent for processing.
        
        Called by trigger listeners. Does NOT execute anything.
        """
        intent.queued_at = datetime.now()
        await self._intent_queue.put(intent)
        _LOGGER.debug(f"Queued intent: {intent.coordinator}/{intent.type}")
    
    async def _process_intents_loop(self) -> None:
        """Main processing loop - runs continuously."""
        while True:
            try:
                # Collect intents (batch with short timeout)
                intents = await self._collect_intents(timeout=0.1)
                
                if intents:
                    await self._process_batch(intents)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.error(f"Intent processing error: {e}", exc_info=True)
                await asyncio.sleep(1)  # Back off on error
    
    async def _collect_intents(self, timeout: float) -> list[Intent]:
        """Collect intents from queue with batching."""
        intents = []
        
        try:
            # Wait for first intent
            intent = await asyncio.wait_for(
                self._intent_queue.get(), 
                timeout=timeout
            )
            intents.append(intent)
            
            # Collect any additional queued intents (non-blocking)
            while not self._intent_queue.empty():
                intents.append(self._intent_queue.get_nowait())
                
        except asyncio.TimeoutError:
            pass  # No intents, that's fine
        
        return intents
    
    async def _process_batch(self, intents: list[Intent]) -> None:
        """Process a batch of intents through coordinators."""
        
        # Build context for all coordinators
        context = await self._build_context()
        
        # Collect proposed actions from coordinators in priority order
        all_actions: list[CoordinatorAction] = []
        
        for coordinator_name in self.PRIORITY_ORDER:
            coordinator = self._coordinators.get(coordinator_name)
            if not coordinator:
                continue
            
            # Get intents for this coordinator
            coord_intents = [
                i for i in intents 
                if i.coordinator == coordinator_name
            ]
            
            # Coordinator evaluates and proposes actions
            try:
                proposed = await coordinator.evaluate(coord_intents, context)
                all_actions.extend(proposed)
            except Exception as e:
                _LOGGER.error(
                    f"Coordinator {coordinator_name} evaluation failed: {e}",
                    exc_info=True
                )
        
        # Resolve conflicts between proposed actions
        approved_actions = self._conflict_resolver.resolve(all_actions)
        
        # Execute approved actions
        for action in approved_actions:
            await self._execute_action(action)
    
    async def _build_context(self) -> CoordinatorContext:
        """Build shared context for coordinator evaluation."""
        return CoordinatorContext(
            house_state=self._house_state,
            house_state_confidence=self._house_state_confidence,
            timestamp=datetime.now(),
            census=await self._get_census_data(),
            # Add more shared context as needed
        )
    
    async def _execute_action(self, action: CoordinatorAction) -> None:
        """Execute a single approved action."""
        
        # Log decision before execution
        decision_id = await self._decision_logger.log_decision(DecisionLog(
            timestamp=datetime.now(),
            coordinator_id=action.coordinator,
            decision_type=action.action_type,
            situation_classified=action.reason,
            urgency=action.severity.value * 25,
            confidence=action.confidence,
            context=action.context,
            action=action.to_dict(),
        ))
        
        # Execute the action
        try:
            await action.execute(self.hass)
            _LOGGER.info(f"Executed: {action.coordinator}/{action.action_type}")
            
            # Schedule compliance check
            if action.device_id:
                await self._compliance_tracker.schedule_check(
                    decision_id,
                    action.device_type,
                    action.device_id,
                    action.commanded_state,
                )
                
        except Exception as e:
            _LOGGER.error(f"Action execution failed: {action} - {e}")
    
    def update_house_state(self, state: HouseState, confidence: float) -> None:
        """Update house state (called by Presence Coordinator)."""
        old_state = self._house_state
        self._house_state = state
        self._house_state_confidence = confidence
        
        if old_state != state:
            _LOGGER.info(f"House state: {old_state.name} → {state.name} ({confidence:.0%})")
            
            # Notify via dispatcher signal
            async_dispatcher_send(
                self.hass,
                SIGNAL_HOUSE_STATE_CHANGED,
                {"state": state, "confidence": confidence, "previous": old_state}
            )
    
    @property
    def house_state(self) -> HouseState:
        """Current house state."""
        return self._house_state
    
    @property
    def notification_manager(self) -> NotificationManager:
        """Access to notification manager for coordinators."""
        return self._notification_manager
```

### Base Coordinator Class

```python
# domain_coordinators/base.py

class BaseCoordinator(ABC):
    """Base class for all domain coordinators."""
    
    COORDINATOR_ID: str = "base"  # Override in subclass
    PRIORITY: int = 0             # Override in subclass
    
    def __init__(self, hass: HomeAssistant, manager: CoordinatorManager):
        self.hass = hass
        self.manager = manager
    
    async def async_setup(self) -> None:
        """
        Setup coordinator.
        
        Subclasses should:
        1. Register state change triggers
        2. Register time-based triggers
        3. Initialize any required state
        """
        pass
    
    @abstractmethod
    async def evaluate(
        self,
        intents: list[Intent],
        context: CoordinatorContext,
    ) -> list[CoordinatorAction]:
        """
        Evaluate intents and propose actions.
        
        Args:
            intents: Intents specifically for this coordinator
            context: Shared context (house state, census, etc.)
        
        Returns:
            List of proposed actions (may be empty)
        """
        pass
    
    def register_state_trigger(
        self,
        entity_id: str,
        intent_type: str,
        condition: Callable[[State, State], bool] | None = None,
    ) -> None:
        """
        Register a state change trigger that queues intents.
        
        Args:
            entity_id: Entity to monitor
            intent_type: Type of intent to create
            condition: Optional filter (old_state, new_state) -> bool
        """
        
        async def _on_state_change(event: Event) -> None:
            if event.data.get("entity_id") != entity_id:
                return
            
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")
            
            # Skip if new state unavailable
            if new_state is None or new_state.state in ("unavailable", "unknown"):
                return
            
            # Apply condition filter
            if condition and not condition(old_state, new_state):
                return
            
            # Queue intent
            await self.manager.queue_intent(Intent(
                coordinator=self.COORDINATOR_ID,
                type=intent_type,
                data={
                    "entity_id": entity_id,
                    "old_state": old_state.state if old_state else None,
                    "new_state": new_state.state,
                    "attributes": dict(new_state.attributes),
                },
            ))
        
        self.hass.bus.async_listen("state_changed", _on_state_change)
    
    def register_time_trigger(
        self,
        interval: timedelta,
        intent_type: str,
    ) -> None:
        """Register a time-based trigger."""
        
        async def _on_interval(now: datetime) -> None:
            await self.manager.queue_intent(Intent(
                coordinator=self.COORDINATOR_ID,
                type=intent_type,
                data={"timestamp": now.isoformat()},
            ))
        
        async_track_time_interval(self.hass, _on_interval, interval)
```

---

## 5. INTENT & ACTION MODEL

### Intent Data Class

```python
@dataclass
class Intent:
    """
    A request to evaluate a situation.
    
    Intents don't cause actions directly - they're inputs
    to coordinator evaluation.
    """
    coordinator: str          # Which coordinator should handle
    type: str                 # Intent type (e.g., "water_leak", "door_opened")
    data: dict = field(default_factory=dict)  # Event-specific data
    queued_at: datetime | None = None
    
    def __str__(self) -> str:
        return f"Intent({self.coordinator}/{self.type})"
```

### Action Data Class

```python
@dataclass
class CoordinatorAction:
    """
    A proposed action from a coordinator.
    
    Actions are evaluated by the Conflict Resolver before execution.
    """
    coordinator: str          # Source coordinator
    action_type: str          # What to do (e.g., "turn_off_water", "lock_door")
    severity: Severity        # CRITICAL, HIGH, MEDIUM, LOW
    confidence: float         # 0.0-1.0 in the trigger condition
    reason: str               # Human-readable explanation
    
    # Target device (if applicable)
    device_type: str | None = None    # "valve", "lock", "climate", etc.
    device_id: str | None = None      # Entity ID
    commanded_state: dict = field(default_factory=dict)
    
    # Context for logging
    context: dict = field(default_factory=dict)
    
    async def execute(self, hass: HomeAssistant) -> None:
        """Execute this action. Override in subclasses for custom logic."""
        raise NotImplementedError("Subclasses must implement execute()")
    
    def to_dict(self) -> dict:
        """Convert to dictionary for logging."""
        return {
            "coordinator": self.coordinator,
            "action_type": self.action_type,
            "severity": self.severity.name,
            "confidence": self.confidence,
            "reason": self.reason,
            "device_type": self.device_type,
            "device_id": self.device_id,
            "commanded_state": self.commanded_state,
        }


class Severity(Enum):
    """Action severity levels."""
    CRITICAL = 4   # Immediate threat to life (fire, CO)
    HIGH = 3       # Significant threat (intrusion, water leak)
    MEDIUM = 2     # Important but not immediate (high CO2, freeze risk)
    LOW = 1        # Advisory (humidity drift, comfort adjustment)
```

### Common Action Types

```python
# Service call action
@dataclass
class ServiceCallAction(CoordinatorAction):
    """Action that calls a Home Assistant service."""
    
    domain: str = ""
    service: str = ""
    service_data: dict = field(default_factory=dict)
    
    async def execute(self, hass: HomeAssistant) -> None:
        await hass.services.async_call(
            self.domain,
            self.service,
            self.service_data,
        )


# Notification action
@dataclass
class NotificationAction(CoordinatorAction):
    """Action that sends a notification."""
    
    message: str = ""
    channels: list[str] = field(default_factory=list)  # ["imessage", "speaker"]
    
    async def execute(self, hass: HomeAssistant) -> None:
        # Handled by NotificationManager
        pass


# Constraint publication action
@dataclass  
class ConstraintAction(CoordinatorAction):
    """Action that publishes constraints to other coordinators."""
    
    constraint_type: str = ""     # "hvac", "lighting", etc.
    constraint_data: dict = field(default_factory=dict)
    
    async def execute(self, hass: HomeAssistant) -> None:
        # Publish via dispatcher signal
        async_dispatcher_send(
            hass,
            f"ura_{self.constraint_type}_constraint",
            self.constraint_data,
        )
```

---

## 6. HOUSE STATE FRAMEWORK

### House States

```python
class HouseState(Enum):
    """Possible states of the house."""
    
    AWAY = "away"               # Nobody home
    ARRIVING = "arriving"       # Someone coming home
    HOME_DAY = "home_day"       # People home, daytime
    HOME_EVENING = "home_evening"  # People home, evening
    HOME_NIGHT = "home_night"   # People home, winding down
    SLEEP = "sleep"             # Household sleeping
    WAKING = "waking"           # Morning transition
    GUEST = "guest"             # Non-family visitors
    VACATION = "vacation"       # Extended away
    EMERGENCY = "emergency"     # Active safety/security event
```

### State Transition Rules

```python
# Valid state transitions
VALID_TRANSITIONS = {
    HouseState.AWAY: [HouseState.ARRIVING, HouseState.VACATION, HouseState.EMERGENCY],
    HouseState.ARRIVING: [HouseState.HOME_DAY, HouseState.HOME_EVENING, HouseState.EMERGENCY],
    HouseState.HOME_DAY: [HouseState.HOME_EVENING, HouseState.AWAY, HouseState.GUEST, HouseState.EMERGENCY],
    HouseState.HOME_EVENING: [HouseState.HOME_NIGHT, HouseState.HOME_DAY, HouseState.AWAY, HouseState.EMERGENCY],
    HouseState.HOME_NIGHT: [HouseState.SLEEP, HouseState.HOME_EVENING, HouseState.EMERGENCY],
    HouseState.SLEEP: [HouseState.WAKING, HouseState.EMERGENCY],
    HouseState.WAKING: [HouseState.HOME_DAY, HouseState.EMERGENCY],
    HouseState.GUEST: [HouseState.HOME_DAY, HouseState.HOME_EVENING, HouseState.AWAY, HouseState.EMERGENCY],
    HouseState.VACATION: [HouseState.ARRIVING, HouseState.EMERGENCY],
    HouseState.EMERGENCY: [HouseState.AWAY, HouseState.HOME_DAY, HouseState.HOME_EVENING],  # Can go anywhere after
}

# Minimum duration before state can change (hysteresis)
MIN_STATE_DURATION = {
    HouseState.ARRIVING: timedelta(minutes=5),
    HouseState.SLEEP: timedelta(minutes=30),
    HouseState.WAKING: timedelta(minutes=15),
    HouseState.GUEST: timedelta(hours=1),
}
```

### How Coordinators Use House State

| House State | Security | Energy | HVAC | Comfort |
|-------------|----------|--------|------|---------|
| AWAY | Full arm | Max conserve | Away preset | Inactive |
| ARRIVING | Disarm path | Pre-condition | Pre-cool/heat | Prepare |
| HOME_DAY | Disarmed | Normal + TOU | User prefs | Active |
| HOME_EVENING | Perimeter | Normal + TOU | User prefs | Active |
| HOME_NIGHT | Perimeter+ | Prepare night | Transition | Dim lights |
| SLEEP | Full home | Night mode | Sleep preset | Sleep prefs |
| WAKING | Disarming | Morning prep | Wake preset | Wake lights |
| GUEST | Modified | Less aggressive | All zones | Default prefs |
| VACATION | Enhanced | Max conserve | Deep setback | Security lights |
| EMERGENCY | All lights on | Override for safety | Override | Emergency |

---

## 7. CONFLICT RESOLUTION

### Purpose

When multiple coordinators propose conflicting actions, the Conflict Resolver determines which actions execute.

### Resolution Algorithm

```python
class ConflictResolver:
    """Resolve conflicts between coordinator actions."""
    
    COORDINATOR_PRIORITY = {
        "safety": 100,
        "security": 80,
        "presence": 60,
        "energy": 40,
        "hvac": 30,
        "comfort": 20,
    }
    
    def resolve(self, actions: list[CoordinatorAction]) -> list[CoordinatorAction]:
        """
        Resolve conflicts and return approved actions.
        
        Algorithm:
        1. Group actions by target device
        2. For each device, select highest-priority action
        3. Consider severity and confidence in close calls
        """
        if not actions:
            return []
        
        # Group by device
        by_device: dict[str, list[CoordinatorAction]] = {}
        no_device: list[CoordinatorAction] = []
        
        for action in actions:
            if action.device_id:
                by_device.setdefault(action.device_id, []).append(action)
            else:
                no_device.append(action)
        
        approved = []
        
        # Resolve per-device conflicts
        for device_id, device_actions in by_device.items():
            winner = self._select_winner(device_actions)
            if winner:
                approved.append(winner)
                
                # Log if there were conflicts
                if len(device_actions) > 1:
                    losers = [a for a in device_actions if a != winner]
                    _LOGGER.info(
                        f"Conflict on {device_id}: {winner.coordinator} won over "
                        f"{[a.coordinator for a in losers]}"
                    )
        
        # Non-device actions (notifications, etc.) - no conflicts
        approved.extend(no_device)
        
        return approved
    
    def _select_winner(
        self, 
        actions: list[CoordinatorAction]
    ) -> CoordinatorAction | None:
        """Select winning action from conflicting set."""
        if not actions:
            return None
        if len(actions) == 1:
            return actions[0]
        
        # Calculate effective priority for each
        scored = [
            (action, self._effective_priority(action))
            for action in actions
        ]
        
        # Sort by priority descending
        scored.sort(key=lambda x: -x[1])
        
        winner, winner_score = scored[0]
        
        # Check if clear winner (20% margin)
        if len(scored) > 1:
            runner_up_score = scored[1][1]
            if winner_score < runner_up_score * 1.2:
                # Close call - log for review
                _LOGGER.warning(
                    f"Close conflict resolution: {winner.coordinator} "
                    f"({winner_score:.1f}) vs {scored[1][0].coordinator} "
                    f"({runner_up_score:.1f})"
                )
        
        return winner
    
    def _effective_priority(self, action: CoordinatorAction) -> float:
        """
        Calculate effective priority.
        
        Formula: base_priority * severity_factor * confidence_factor
        """
        base = self.COORDINATOR_PRIORITY.get(action.coordinator, 10)
        severity_factor = action.severity.value / 4.0  # 0.25 to 1.0
        confidence_factor = 0.5 + (action.confidence * 0.5)  # 0.5 to 1.0
        
        return base * severity_factor * confidence_factor
```

### Conflict Examples

```python
# Example 1: Safety vs Energy (Safety wins)
# Freeze risk detected during peak TOU

safety_action = CoordinatorAction(
    coordinator="safety",
    action_type="override_hvac_heat",
    severity=Severity.HIGH,       # Freeze risk
    confidence=0.85,
    device_id="climate.zone_3",
    commanded_state={"hvac_mode": "heat", "target_temp_low": 65},
)
# Effective: 100 * 0.75 * 0.925 = 69.4

energy_action = CoordinatorAction(
    coordinator="energy",
    action_type="coast_hvac",
    severity=Severity.MEDIUM,     # Peak TOU
    confidence=0.95,
    device_id="climate.zone_3",
    commanded_state={"target_temp_high": 78},
)
# Effective: 40 * 0.5 * 0.975 = 19.5

# Winner: Safety (69.4 >> 19.5)


# Example 2: Security vs Comfort (Security wins)
# Intrusion detected, Comfort wants to turn on lights for reading

security_action = CoordinatorAction(
    coordinator="security",
    action_type="security_lights",
    severity=Severity.HIGH,
    confidence=0.70,              # Motion but unconfirmed
    device_id="light.living_room",
    commanded_state={"state": "on", "brightness": 255, "rgb_color": [255, 0, 0]},
)
# Effective: 80 * 0.75 * 0.85 = 51.0

comfort_action = CoordinatorAction(
    coordinator="comfort",
    action_type="reading_light",
    severity=Severity.LOW,
    confidence=0.90,
    device_id="light.living_room",
    commanded_state={"state": "on", "brightness": 180, "color_temp": 300},
)
# Effective: 20 * 0.25 * 0.95 = 4.75

# Winner: Security (51.0 >> 4.75)
```

---

## 8. COMMUNICATION PATTERNS

### Pattern 1: Triggers → Intents (Event Listeners)

```python
# Coordinator registers trigger, doesn't act directly
class SafetyCoordinator(BaseCoordinator):
    
    async def async_setup(self) -> None:
        # Water leak sensor
        self.register_state_trigger(
            entity_id="binary_sensor.water_leak_laundry",
            intent_type="water_leak",
            condition=lambda old, new: new.state == "on",
        )
        
        # Smoke detector
        self.register_state_trigger(
            entity_id="binary_sensor.smoke_kitchen",
            intent_type="smoke_detected",
            condition=lambda old, new: new.state == "on",
        )
```

### Pattern 2: Data Sharing (Dispatcher Signals)

For sharing data (not triggering actions):

```python
# Signal definitions
SIGNAL_HOUSE_STATE_CHANGED = "ura_house_state_changed"
SIGNAL_ENERGY_CONSTRAINT = "ura_energy_constraint"
SIGNAL_CENSUS_UPDATED = "ura_census_updated"

# Publishing (Presence Coordinator)
async_dispatcher_send(
    self.hass,
    SIGNAL_HOUSE_STATE_CHANGED,
    {"state": HouseState.SLEEP, "confidence": 0.85}
)

# Subscribing (Security Coordinator)
async_dispatcher_connect(
    self.hass,
    SIGNAL_HOUSE_STATE_CHANGED,
    self._on_house_state_changed,
)

# Handler queues intent, doesn't act
async def _on_house_state_changed(self, data: dict) -> None:
    # React by queueing intent, not executing
    await self.manager.queue_intent(Intent(
        coordinator="security",
        type="house_state_changed",
        data=data,
    ))
```

### Pattern 3: Coordinator-to-Coordinator Signals

For Energy → HVAC constraints:

```python
# Energy Coordinator publishes constraint
class EnergyCoordinator(BaseCoordinator):
    
    async def _publish_hvac_constraint(self, constraint: HVACConstraints) -> None:
        async_dispatcher_send(
            self.hass,
            SIGNAL_ENERGY_CONSTRAINT,
            constraint.to_dict(),
        )

# HVAC Coordinator subscribes
class HVACCoordinator(BaseCoordinator):
    
    async def async_setup(self) -> None:
        async_dispatcher_connect(
            self.hass,
            SIGNAL_ENERGY_CONSTRAINT,
            self._on_energy_constraint,
        )
    
    async def _on_energy_constraint(self, data: dict) -> None:
        self._current_constraint = HVACConstraints.from_dict(data)
        # Apply constraint in next evaluation cycle
```

---

## 9. SHARED SERVICES

### Notification Manager

See **NOTIFICATION_MANAGER.md** for full design.

| Channel | Status | Priority Support |
|---------|--------|------------------|
| iMessage | Available now | CRITICAL, HIGH, MEDIUM |
| Speakers (TTS) | Configure later | CRITICAL, HIGH |
| Lights (visual) | Configure later | All severities |
| Push (HA app) | Optional | All severities |

### Conflict Resolver

Built into Coordinator Manager (Section 7).

### Decision Logger

See **COORDINATOR_DIAGNOSTICS_FRAMEWORK.md**.

### Compliance Tracker

See **COORDINATOR_DIAGNOSTICS_FRAMEWORK.md**.

---

## 10. PERSISTENCE & RECOVERY

### What's Persisted

| Data | Storage | Purpose |
|------|---------|---------|
| House State | SQLite | Recover state on restart |
| Coordinator Parameters | SQLite | Learned values |
| Decision Log | SQLite | Audit trail |
| Compliance Log | SQLite | Override detection |
| Pending Actions | SQLite | Recovery if crash mid-execution |

### Recovery on Startup

```python
class CoordinatorManager:
    
    async def recover_state(self) -> None:
        """Recover state from SQLite on HA startup."""
        
        # 1. Load last known house state
        last_state = await self._db.get_last_house_state()
        if last_state:
            elapsed = datetime.now() - last_state.timestamp
            
            # If recent, trust it
            if elapsed < timedelta(hours=1):
                self._house_state = last_state.state
                self._house_state_confidence = last_state.confidence * 0.8  # Decay
            else:
                # Stale - re-infer from Census
                self._house_state = HouseState.AWAY  # Safe default
                self._house_state_confidence = 0.5
        
        # 2. Load any pending actions
        pending = await self._db.get_pending_actions()
        for action in pending:
            _LOGGER.warning(f"Found pending action from before restart: {action}")
            # Don't auto-execute - conditions may have changed
            # Instead, queue intent for re-evaluation
            await self.queue_intent(Intent(
                coordinator=action.coordinator,
                type="recovery_reevaluate",
                data=action.to_dict(),
            ))
        
        # 3. Load learned parameters into coordinators
        for name, coordinator in self._coordinators.items():
            if hasattr(coordinator, 'load_learned_parameters'):
                await coordinator.load_learned_parameters()
```

---

## 11. HOME ASSISTANT INTEGRATION

### Integration Setup

```python
# __init__.py

async def async_setup_entry(
    hass: HomeAssistant, 
    entry: ConfigEntry
) -> bool:
    """Set up URA from a config entry."""
    
    # Initialize database
    db_path = hass.config.path("ura_coordinators.db")
    
    # Create Coordinator Manager
    manager = CoordinatorManager(hass, db_path)
    
    # Recover state from previous session
    await manager.recover_state()
    
    # Initialize all coordinators
    await manager.async_setup()
    
    # Store for access by other components
    hass.data[DOMAIN] = {
        "manager": manager,
        "coordinators": manager._coordinators,
    }
    
    # Setup platforms (sensors, etc.)
    await hass.config_entries.async_forward_entry_setups(
        entry, ["sensor", "binary_sensor"]
    )
    
    return True


async def async_unload_entry(
    hass: HomeAssistant, 
    entry: ConfigEntry
) -> bool:
    """Unload URA."""
    manager = hass.data[DOMAIN]["manager"]
    
    # Save current state
    await manager.save_state()
    
    # Cancel processing task
    manager._processing_task.cancel()
    
    # Unload platforms
    await hass.config_entries.async_unload_platforms(
        entry, ["sensor", "binary_sensor"]
    )
    
    return True
```

### Sensors Created

Each coordinator creates diagnostic sensors:

```yaml
# Manager-level sensors
sensor.ura_coordinator_manager:
  state: "running"
  attributes:
    intents_processed_today: 1247
    actions_executed_today: 89
    conflicts_resolved_today: 12
    last_intent_timestamp: "2026-01-24T16:30:15"

sensor.ura_house_state:
  state: "HOME_EVENING"
  attributes:
    confidence: 0.92
    duration: "2h 15m"
    previous_state: "HOME_DAY"
    occupants: ["oji", "spouse"]

# Per-coordinator sensors (see individual docs)
sensor.ura_safety_status: ...
sensor.ura_security_status: ...
sensor.ura_energy_situation: ...
sensor.ura_hvac_mode: ...
sensor.ura_comfort_score: ...
```

---

## 12. COORDINATOR SUMMARY

| Coordinator | Document | Scope | Key Responsibilities |
|-------------|----------|-------|---------------------|
| **Presence** | PRESENCE_COORDINATOR.md | House | State inference, transitions |
| **Safety** | SAFETY_COORDINATOR.md | House | Environmental hazards |
| **Security** | SECURITY_COORDINATOR.md | House | Intrusion, access control |
| **Energy** | ENERGY_COORDINATOR_DESIGN.md | House | TOU, battery, load mgmt |
| **HVAC** | HVAC_COORDINATOR_DESIGN.md | Zone | Climate control |
| **Comfort** | COMFORT_COORDINATOR.md | Room | Room-level comfort |

### Shared Services

| Service | Document | Purpose |
|---------|----------|---------|
| Notification Manager | NOTIFICATION_MANAGER.md | Multi-channel alerts |
| Conflict Resolver | (This document, Section 7) | Priority arbitration |
| Decision Logger | COORDINATOR_DIAGNOSTICS_FRAMEWORK.md | Audit trail |
| Compliance Tracker | COORDINATOR_DIAGNOSTICS_FRAMEWORK.md | Override detection |

---

**Document Status:** Design Complete  
**Next Steps:** Create/update individual coordinator design documents

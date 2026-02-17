# COMFORT COORDINATOR DESIGN

**Version:** 1.0  
**Status:** Design Complete  
**Last Updated:** 2026-01-24  
**Scope:** Room-level comfort management

---

## TABLE OF CONTENTS

1. [Overview](#1-overview)
2. [Scope & Hierarchy](#2-scope--hierarchy)
3. [Comfort Dimensions](#3-comfort-dimensions)
4. [Person Preferences](#4-person-preferences)
5. [Room Comfort Score](#5-room-comfort-score)
6. [Controlled Devices](#6-controlled-devices)
7. [HVAC Signaling](#7-hvac-signaling)
8. [Circadian Lighting](#8-circadian-lighting)
9. [Implementation](#9-implementation)
10. [Sensors & Entities](#10-sensors--entities)
11. [Diagnostics](#11-diagnostics)

---

## 1. OVERVIEW

### Purpose

The Comfort Coordinator **manages room-level comfort** by:
- Monitoring temperature, humidity, lighting per room
- Applying person-specific preferences (who's in the room)
- Controlling room-level devices (fans, heaters, lights)
- Signaling HVAC when zone adjustment needed

### Design Principles

| Principle | Description |
|-----------|-------------|
| **Room-Level Focus** | Operates at individual room granularity |
| **Person-Aware** | Applies preferences based on Census occupancy |
| **Local First** | Use room devices before requesting HVAC changes |
| **Non-Intrusive** | Comfort adjustments shouldn't disrupt activities |
| **Energy Aware** | Respects Energy Coordinator constraints |

### Scope Hierarchy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         COMFORT HIERARCHY                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ENERGY COORDINATOR (House Level)                                           │
│  └─► Publishes: EnergyConstraints                                           │
│      • Peak/off-peak periods                                                │
│      • Conservation mode                                                    │
│      • Load priorities                                                      │
│           │                                                                 │
│           ▼                                                                 │
│  HVAC COORDINATOR (Zone Level - 3 zones)                                    │
│  └─► Controls: Carrier Infinity thermostats                                │
│      • Responds to Energy constraints                                      │
│      • Responds to Comfort requests                                        │
│      • Aggregates room needs → zone setpoints                              │
│           │                                                                 │
│           ▼                                                                 │
│  COMFORT COORDINATOR (Room Level - 20+ rooms)                               │
│  └─► Controls: Room fans, heaters, lights                                  │
│      • Monitors per-room conditions                                        │
│      • Applies person preferences                                          │
│      • Signals HVAC when zone adjustment needed                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. SCOPE & HIERARCHY

### What Comfort Controls

| Device Type | Examples | Control Scope |
|-------------|----------|---------------|
| Ceiling Fans | 20 fans across house | Speed, direction |
| Portable Fans | Box fans, tower fans | On/off, speed |
| Space Heaters | Portable heaters | On/off, temp |
| Dehumidifiers | Room dehumidifiers | On/off, target |
| Lighting | Room lights | Brightness, color temp |

### What Comfort Does NOT Control

| Device | Controlled By |
|--------|---------------|
| HVAC thermostats | HVAC Coordinator |
| Whole-house ventilation | HVAC Coordinator |
| Pool equipment | Energy Coordinator |
| Security lights | Security Coordinator |

### Comfort → HVAC Interaction

```python
# Comfort can REQUEST zone adjustments from HVAC
# HVAC decides whether to honor based on Energy constraints

@dataclass
class ComfortRequest:
    """Request from Comfort to HVAC."""
    
    room_id: str
    zone_id: str              # Which HVAC zone
    request_type: str         # "cooling", "heating", "ventilation"
    current_temp: float
    target_temp: float
    priority: str             # "low", "medium", "high"
    reason: str               # "occupant_too_warm", "humidity_high"
    
    
# HVAC responses
class HVACResponse(Enum):
    HONORED = "honored"           # Request will be fulfilled
    DENIED_ENERGY = "denied_energy"   # Energy constraints prevent
    DENIED_ZONE = "denied_zone"       # Would affect other rooms negatively
    PARTIAL = "partial"           # Partial adjustment made
```

---

## 3. COMFORT DIMENSIONS

### What Comfort Monitors

```python
@dataclass
class RoomConditions:
    """Current conditions in a room."""
    
    room_id: str
    
    # Temperature
    temperature: float | None     # Current temp (°F)
    temperature_trend: float      # °F/hour change rate
    
    # Humidity
    humidity: float | None        # Current RH%
    humidity_trend: float         # %/hour change rate
    
    # Lighting
    light_level: float | None     # Lux if sensor available
    lights_on: bool
    light_brightness: int | None  # 0-255
    light_color_temp: int | None  # Kelvin
    
    # Occupancy (from Census)
    occupants: list[str]          # Person IDs in room
    occupancy_duration: timedelta # How long occupied
    
    # Timestamps
    last_update: datetime
```

### Comfort Targets

```python
@dataclass
class ComfortTargets:
    """Target conditions for a room."""
    
    # Temperature range (allows hysteresis)
    temp_min: float = 70.0        # Too cold below this
    temp_max: float = 76.0        # Too warm above this
    temp_ideal: float = 73.0      # Perfect
    
    # Humidity range
    humidity_min: float = 30.0
    humidity_max: float = 55.0
    humidity_ideal: float = 45.0
    
    # Lighting (context-dependent)
    light_min_lux: float = 300    # Minimum for task lighting
    circadian_enabled: bool = True
```

---

## 4. PERSON PREFERENCES

### Preference Model

```python
@dataclass
class PersonPreferences:
    """Comfort preferences for a person."""
    
    person_id: str
    
    # Temperature preferences
    cool_preference: float = 74.0   # Preferred cooling setpoint
    heat_preference: float = 70.0   # Preferred heating setpoint
    temp_sensitivity: str = "normal"  # "sensitive", "normal", "tolerant"
    
    # Humidity preferences
    humidity_max: float = 55.0      # Maximum comfortable humidity
    
    # Lighting preferences
    circadian_enabled: bool = True  # Follow circadian rhythm
    brightness_preference: str = "normal"  # "dim", "normal", "bright"
    
    # Sleep preferences
    sleep_temp: float = 68.0        # Preferred sleep temperature
    sleep_fan: bool = True          # Fan during sleep
    sleep_fan_speed: str = "low"    # "low", "medium", "high"


# Example configurations
PERSON_PREFERENCES = {
    "oji": PersonPreferences(
        person_id="oji",
        cool_preference=74.0,
        heat_preference=70.0,
        humidity_max=55.0,
        circadian_enabled=True,
    ),
    "spouse": PersonPreferences(
        person_id="spouse",
        cool_preference=72.0,
        heat_preference=71.0,
        humidity_max=50.0,
        circadian_enabled=False,
        temp_sensitivity="sensitive",
    ),
    "default": PersonPreferences(
        person_id="default",
        cool_preference=74.0,
        heat_preference=70.0,
    ),
}
```

### Preference Resolution

When multiple people occupy a room:

```python
class PreferenceResolver:
    """Resolve preferences when multiple occupants."""
    
    def resolve(
        self, 
        occupants: list[str],
        house_state: HouseState,
    ) -> ComfortTargets:
        """
        Resolve preferences for multiple occupants.
        
        Strategy:
        - Temperature: Use warmest cool_preference (avoid overcooling)
        - Humidity: Use lowest humidity_max (most restrictive)
        - Lighting: Follow most sensitive person
        """
        
        if not occupants:
            return self._get_default_targets(house_state)
        
        prefs = [
            PERSON_PREFERENCES.get(p, PERSON_PREFERENCES["default"])
            for p in occupants
        ]
        
        # Temperature: Warmest preference wins (save energy, avoid complaints)
        temp_ideal = max(p.cool_preference for p in prefs)
        
        # Humidity: Most restrictive wins
        humidity_max = min(p.humidity_max for p in prefs)
        
        # Circadian: Enabled if any occupant wants it
        circadian = any(p.circadian_enabled for p in prefs)
        
        return ComfortTargets(
            temp_min=temp_ideal - 3,
            temp_max=temp_ideal + 2,
            temp_ideal=temp_ideal,
            humidity_max=humidity_max,
            circadian_enabled=circadian,
        )
```

---

## 5. ROOM COMFORT SCORE

### Scoring Model

```python
class ComfortScorer:
    """Calculate room comfort scores."""
    
    def score(
        self, 
        conditions: RoomConditions, 
        targets: ComfortTargets
    ) -> ComfortScore:
        """
        Calculate comfort score (0-100).
        
        100 = Perfect comfort
        80+ = Comfortable
        60-80 = Acceptable
        40-60 = Uncomfortable
        <40 = Very uncomfortable
        """
        
        scores = []
        
        # Temperature score (40% weight)
        if conditions.temperature is not None:
            temp_score = self._score_temperature(
                conditions.temperature, targets
            )
            scores.append(("temperature", temp_score, 0.40))
        
        # Humidity score (30% weight)
        if conditions.humidity is not None:
            humidity_score = self._score_humidity(
                conditions.humidity, targets
            )
            scores.append(("humidity", humidity_score, 0.30))
        
        # Lighting score (30% weight)
        if conditions.light_level is not None:
            light_score = self._score_lighting(
                conditions.light_level,
                conditions.light_color_temp,
                targets,
            )
            scores.append(("lighting", light_score, 0.30))
        
        # Weighted average
        total_weight = sum(s[2] for s in scores)
        if total_weight > 0:
            overall = sum(s[1] * s[2] for s in scores) / total_weight
        else:
            overall = 50.0  # No data
        
        return ComfortScore(
            overall=overall,
            temperature=next((s[1] for s in scores if s[0] == "temperature"), None),
            humidity=next((s[1] for s in scores if s[0] == "humidity"), None),
            lighting=next((s[1] for s in scores if s[0] == "lighting"), None),
        )
    
    def _score_temperature(
        self, 
        temp: float, 
        targets: ComfortTargets
    ) -> float:
        """Score temperature (0-100)."""
        
        if targets.temp_min <= temp <= targets.temp_max:
            # Within range - score based on distance from ideal
            distance = abs(temp - targets.temp_ideal)
            max_distance = max(
                targets.temp_ideal - targets.temp_min,
                targets.temp_max - targets.temp_ideal,
            )
            return 100 - (distance / max_distance) * 20  # 80-100
        
        elif temp < targets.temp_min:
            # Too cold
            distance = targets.temp_min - temp
            return max(0, 80 - distance * 10)
        
        else:
            # Too warm
            distance = temp - targets.temp_max
            return max(0, 80 - distance * 10)
```

### Score Publishing

```yaml
# Per-room comfort score sensors
sensor.ura_comfort_score_living_room:
  state: 85
  unit_of_measurement: "%"
  attributes:
    temperature_score: 90
    humidity_score: 80
    lighting_score: 85
    occupants: ["oji", "spouse"]
    active_adjustments: ["ceiling_fan_medium"]

sensor.ura_comfort_score_master_bedroom:
  state: 72
  attributes:
    temperature_score: 65  # Too warm
    humidity_score: 80
    lighting_score: null   # No sensor
    recommendation: "Turn on ceiling fan"
```

---

## 6. CONTROLLED DEVICES

### Ceiling Fans

```python
class CeilingFanController:
    """Control ceiling fans for comfort."""
    
    # Speed mapping
    SPEEDS = {
        "off": 0,
        "low": 33,
        "medium": 66,
        "high": 100,
    }
    
    async def adjust_for_comfort(
        self,
        room_id: str,
        conditions: RoomConditions,
        targets: ComfortTargets,
        house_state: HouseState,
    ) -> CoordinatorAction | None:
        
        fan_entity = self._get_fan_entity(room_id)
        if not fan_entity:
            return None
        
        # Don't run fans in unoccupied rooms (unless house state dictates)
        if not conditions.occupants and house_state != HouseState.AWAY:
            if self._is_fan_on(fan_entity):
                return self._turn_off(fan_entity, "Room unoccupied")
            return None
        
        temp = conditions.temperature
        if temp is None:
            return None
        
        # Determine appropriate fan speed
        if temp > targets.temp_max + 2:
            speed = "high"
            reason = f"Room very warm ({temp}°F)"
        elif temp > targets.temp_max:
            speed = "medium"
            reason = f"Room warm ({temp}°F)"
        elif temp > targets.temp_ideal:
            speed = "low"
            reason = f"Slight cooling ({temp}°F)"
        else:
            speed = "off"
            reason = "Temperature comfortable"
        
        # Sleep mode: Respect preferences
        if house_state == HouseState.SLEEP:
            for occupant in conditions.occupants:
                prefs = PERSON_PREFERENCES.get(occupant)
                if prefs and prefs.sleep_fan:
                    speed = prefs.sleep_fan_speed
                    reason = f"Sleep preference: {speed}"
                    break
        
        current_speed = self._get_current_speed(fan_entity)
        if speed == current_speed:
            return None
        
        return ServiceCallAction(
            coordinator="comfort",
            action_type="ceiling_fan",
            severity=Severity.LOW,
            confidence=0.85,
            reason=reason,
            device_type="fan",
            device_id=fan_entity,
            commanded_state={"speed": speed},
            domain="fan",
            service="set_percentage",
            service_data={
                "entity_id": fan_entity,
                "percentage": self.SPEEDS[speed],
            },
        )
```

### Room Heaters/Coolers

```python
class PortableDeviceController:
    """Control portable heaters/fans/dehumidifiers."""
    
    async def adjust(
        self,
        room_id: str,
        conditions: RoomConditions,
        targets: ComfortTargets,
    ) -> list[CoordinatorAction]:
        
        actions = []
        
        # Portable heater
        heater = self._get_heater(room_id)
        if heater and conditions.temperature:
            if conditions.temperature < targets.temp_min - 2:
                actions.append(self._turn_on(heater, "Room too cold"))
            elif conditions.temperature > targets.temp_min:
                actions.append(self._turn_off(heater, "Temperature OK"))
        
        # Dehumidifier
        dehumidifier = self._get_dehumidifier(room_id)
        if dehumidifier and conditions.humidity:
            if conditions.humidity > targets.humidity_max:
                actions.append(self._turn_on(dehumidifier, "Humidity high"))
            elif conditions.humidity < targets.humidity_max - 10:
                actions.append(self._turn_off(dehumidifier, "Humidity OK"))
        
        return actions
```

---

## 7. HVAC SIGNALING

### When to Signal HVAC

```python
class HVACSignaler:
    """Determine when to request HVAC zone adjustments."""
    
    SIGNAL_THRESHOLDS = {
        # Signal HVAC when room-level devices can't keep up
        "temp_delta_cooling": 3.0,  # °F above target despite fan
        "temp_delta_heating": 3.0,  # °F below target despite heater
        "sustained_duration": timedelta(minutes=15),  # Must persist
    }
    
    async def should_signal(
        self,
        room_id: str,
        conditions: RoomConditions,
        targets: ComfortTargets,
        room_devices_active: bool,
    ) -> ComfortRequest | None:
        """
        Determine if HVAC zone adjustment is needed.
        
        Only signal if:
        1. Room-level devices are already active
        2. Condition has persisted for sustained duration
        3. Delta exceeds threshold
        """
        
        if not room_devices_active:
            # Try room devices first
            return None
        
        temp = conditions.temperature
        if temp is None:
            return None
        
        zone_id = self._get_zone_for_room(room_id)
        
        # Too warm despite fans
        if temp > targets.temp_max + self.SIGNAL_THRESHOLDS["temp_delta_cooling"]:
            if self._condition_sustained(room_id, "too_warm"):
                return ComfortRequest(
                    room_id=room_id,
                    zone_id=zone_id,
                    request_type="cooling",
                    current_temp=temp,
                    target_temp=targets.temp_ideal,
                    priority="medium",
                    reason=f"Room {temp}°F despite fans",
                )
        
        # Too cold despite heater
        if temp < targets.temp_min - self.SIGNAL_THRESHOLDS["temp_delta_heating"]:
            if self._condition_sustained(room_id, "too_cold"):
                return ComfortRequest(
                    room_id=room_id,
                    zone_id=zone_id,
                    request_type="heating",
                    current_temp=temp,
                    target_temp=targets.temp_ideal,
                    priority="medium",
                    reason=f"Room {temp}°F despite heater",
                )
        
        return None
```

### HVAC Response Handling

```python
async def _on_hvac_response(self, response: dict) -> None:
    """Handle HVAC coordinator response to comfort request."""
    
    room_id = response["room_id"]
    result = HVACResponse(response["result"])
    
    if result == HVACResponse.DENIED_ENERGY:
        # HVAC denied due to energy constraints
        # Maximize room-level devices instead
        _LOGGER.info(f"HVAC denied for {room_id} (energy) - maximizing room devices")
        await self._maximize_room_devices(room_id)
        
    elif result == HVACResponse.DENIED_ZONE:
        # Would affect other rooms negatively
        _LOGGER.info(f"HVAC denied for {room_id} (zone conflict)")
        await self._maximize_room_devices(room_id)
        
    elif result == HVACResponse.PARTIAL:
        # Partial adjustment made
        _LOGGER.info(f"HVAC partial adjustment for {room_id}")
```

---

## 8. CIRCADIAN LIGHTING

### Circadian Model

```python
class CircadianLighting:
    """Manage circadian-appropriate lighting."""
    
    # Color temperature by time of day (Kelvin)
    CIRCADIAN_SCHEDULE = {
        # Early morning: Warm, gentle
        (5, 7): {"color_temp": 2700, "brightness_pct": 50},
        # Morning: Energizing
        (7, 9): {"color_temp": 4000, "brightness_pct": 80},
        # Day: Bright, neutral
        (9, 17): {"color_temp": 5000, "brightness_pct": 100},
        # Evening: Warming
        (17, 20): {"color_temp": 3500, "brightness_pct": 80},
        # Night: Warm, dimming
        (20, 22): {"color_temp": 2700, "brightness_pct": 60},
        # Late night: Very warm, very dim
        (22, 24): {"color_temp": 2200, "brightness_pct": 30},
        (0, 5): {"color_temp": 2200, "brightness_pct": 20},
    }
    
    def get_target(self, hour: int) -> dict:
        """Get circadian target for current hour."""
        for (start, end), target in self.CIRCADIAN_SCHEDULE.items():
            if start <= hour < end:
                return target
        return {"color_temp": 3500, "brightness_pct": 70}
    
    async def adjust_room_lighting(
        self,
        room_id: str,
        occupants: list[str],
        house_state: HouseState,
    ) -> list[CoordinatorAction]:
        """Adjust lighting for circadian rhythm."""
        
        actions = []
        
        # Check if any occupant has circadian enabled
        circadian_enabled = any(
            PERSON_PREFERENCES.get(p, PERSON_PREFERENCES["default"]).circadian_enabled
            for p in occupants
        )
        
        if not circadian_enabled:
            return actions
        
        # Don't adjust during sleep
        if house_state == HouseState.SLEEP:
            return actions
        
        # Get target for current time
        hour = datetime.now().hour
        target = self.get_target(hour)
        
        # Get lights in room
        lights = self._get_room_lights(room_id)
        
        for light in lights:
            if self._supports_color_temp(light):
                current = self._get_current_color_temp(light)
                target_temp = target["color_temp"]
                
                # Only adjust if significantly different (avoid flicker)
                if current and abs(current - target_temp) > 200:
                    actions.append(ServiceCallAction(
                        coordinator="comfort",
                        action_type="circadian_lighting",
                        severity=Severity.LOW,
                        confidence=0.90,
                        reason=f"Circadian: {target_temp}K at {hour}:00",
                        device_id=light,
                        domain="light",
                        service="turn_on",
                        service_data={
                            "entity_id": light,
                            "color_temp_kelvin": target_temp,
                        },
                    ))
        
        return actions
```

---

## 9. IMPLEMENTATION

```python
class ComfortCoordinator(BaseCoordinator):
    """Room-level comfort management."""
    
    COORDINATOR_ID = "comfort"
    PRIORITY = 20  # Lowest priority
    
    def __init__(self, hass: HomeAssistant, manager: CoordinatorManager):
        super().__init__(hass, manager)
        
        self._preference_resolver = PreferenceResolver()
        self._comfort_scorer = ComfortScorer()
        self._fan_controller = CeilingFanController()
        self._portable_controller = PortableDeviceController()
        self._hvac_signaler = HVACSignaler()
        self._circadian = CircadianLighting()
        
        # Room conditions cache
        self._room_conditions: dict[str, RoomConditions] = {}
        self._room_scores: dict[str, ComfortScore] = {}
    
    async def async_setup(self) -> None:
        """Setup comfort coordinator."""
        
        # Subscribe to Census updates (know who's where)
        async_dispatcher_connect(
            self.hass,
            SIGNAL_CENSUS_UPDATED,
            self._on_census_update,
        )
        
        # Subscribe to HVAC responses
        async_dispatcher_connect(
            self.hass,
            SIGNAL_HVAC_RESPONSE,
            self._on_hvac_response,
        )
        
        # Register temperature sensors
        for sensor in self._temperature_sensors:
            self.register_state_trigger(
                entity_id=sensor,
                intent_type="temperature_change",
            )
        
        # Register humidity sensors
        for sensor in self._humidity_sensors:
            self.register_state_trigger(
                entity_id=sensor,
                intent_type="humidity_change",
            )
        
        # Periodic re-evaluation (every 5 minutes)
        self.register_time_trigger(
            interval=timedelta(minutes=5),
            intent_type="periodic_comfort_check",
        )
        
        # Circadian lighting updates (every 15 minutes)
        self.register_time_trigger(
            interval=timedelta(minutes=15),
            intent_type="circadian_update",
        )
    
    async def evaluate(
        self,
        intents: list[Intent],
        context: CoordinatorContext,
    ) -> list[CoordinatorAction]:
        
        actions = []
        
        for intent in intents:
            if intent.type in ("temperature_change", "humidity_change"):
                room_id = self._get_room_for_sensor(intent.data["entity_id"])
                if room_id:
                    await self._update_room_conditions(room_id)
                    room_actions = await self._evaluate_room(room_id, context)
                    actions.extend(room_actions)
                    
            elif intent.type == "periodic_comfort_check":
                # Check all occupied rooms
                for room_id in self._get_occupied_rooms(context.census):
                    room_actions = await self._evaluate_room(room_id, context)
                    actions.extend(room_actions)
                    
            elif intent.type == "circadian_update":
                # Update circadian lighting
                for room_id in self._get_occupied_rooms(context.census):
                    occupants = context.census.room_occupancy.get(room_id, [])
                    light_actions = await self._circadian.adjust_room_lighting(
                        room_id, occupants, context.house_state
                    )
                    actions.extend(light_actions)
        
        return actions
    
    async def _evaluate_room(
        self,
        room_id: str,
        context: CoordinatorContext,
    ) -> list[CoordinatorAction]:
        """Evaluate and adjust comfort for a room."""
        
        actions = []
        
        # Get current conditions
        conditions = self._room_conditions.get(room_id)
        if not conditions:
            return actions
        
        # Get occupants
        occupants = context.census.room_occupancy.get(room_id, [])
        conditions.occupants = occupants
        
        # Resolve preferences
        targets = self._preference_resolver.resolve(occupants, context.house_state)
        
        # Calculate comfort score
        score = self._comfort_scorer.score(conditions, targets)
        self._room_scores[room_id] = score
        
        # Adjust ceiling fan
        fan_action = await self._fan_controller.adjust_for_comfort(
            room_id, conditions, targets, context.house_state
        )
        if fan_action:
            actions.append(fan_action)
        
        # Adjust portable devices
        portable_actions = await self._portable_controller.adjust(
            room_id, conditions, targets
        )
        actions.extend(portable_actions)
        
        # Check if HVAC signal needed
        room_devices_active = bool(fan_action) or bool(portable_actions)
        hvac_request = await self._hvac_signaler.should_signal(
            room_id, conditions, targets, room_devices_active
        )
        if hvac_request:
            # Publish request to HVAC coordinator
            async_dispatcher_send(
                self.hass,
                SIGNAL_COMFORT_REQUEST,
                hvac_request.__dict__,
            )
        
        return actions
```

---

## 10. SENSORS & ENTITIES

### Per-Room Sensors

```yaml
sensor.ura_comfort_score_living_room:
  state: 85
  unit_of_measurement: "%"
  attributes:
    temperature: 74.2
    humidity: 48
    temperature_score: 90
    humidity_score: 80
    lighting_score: 85
    occupants: ["oji", "spouse"]
    target_temp: 74
    ceiling_fan: "medium"

sensor.ura_comfort_score_master_bedroom:
  state: 72
  attributes:
    temperature: 77.5
    temperature_score: 65
    recommendation: "ceiling_fan_high"
```

### House-Level Sensors

```yaml
sensor.ura_comfort_average:
  state: 82
  unit_of_measurement: "%"
  attributes:
    occupied_rooms: 5
    rooms_comfortable: 4
    rooms_uncomfortable: 1
    worst_room: "master_bedroom"
    worst_score: 72
```

---

## 11. DIAGNOSTICS

```yaml
sensor.ura_comfort_diagnostics:
  state: "healthy"
  attributes:
    rooms_monitored: 12
    fans_controlled: 8
    circadian_lights: 15
    hvac_requests_today: 3
    hvac_requests_honored: 2
    avg_comfort_score_24h: 84
    adjustments_today: 47
```

---

## KEY DESIGN QUESTIONS

### Q1: Room-to-Zone Mapping

**Question:** How do rooms map to HVAC zones?

**Needed:** Mapping of each room to its Carrier Infinity zone for HVAC signaling.

Example:
```python
ROOM_TO_ZONE = {
    "living_room": "zone_1",
    "kitchen": "zone_1",
    "master_bedroom": "zone_2",
    "office": "zone_2",
    "guest_bedroom": "zone_3",
    # etc.
}
```

---

### Q2: Temperature Sensor Availability

**Question:** Which rooms have temperature sensors?

**Current Assumption:** Temperature sensors available in most rooms (from ESP32 sensors, thermostats, or other devices).

**Recommendation Needed:** List of rooms with temperature/humidity sensors.

---

### Q3: Circadian Light Selection

**Question:** Which lights should follow circadian rhythm?

**Options:**
1. All smart bulbs with color temperature control
2. Only main room lights (not accent/task)
3. Manually selected lights per room

**Recommendation Needed:** Circadian light policy?

---

**Document Status:** Design Complete - Pending Answers  
**Priority:** 20 (Lowest - defers to all others)  
**Dependencies:** Census, HVAC Coordinator, Energy Constraints

# SAFETY COORDINATOR DESIGN

**Version:** 1.0  
**Status:** Design Complete  
**Last Updated:** 2026-01-24  
**Scope:** Environmental hazard detection and response

---

## TABLE OF CONTENTS

1. [Overview](#1-overview)
2. [Hazard Types](#2-hazard-types)
3. [Severity Framework](#3-severity-framework)
4. [Sensor Requirements](#4-sensor-requirements)
5. [Detection Logic](#5-detection-logic)
6. [Response Actions](#6-response-actions)
7. [Notification Strategy](#7-notification-strategy)
8. [Override Authority](#8-override-authority)
9. [Implementation](#9-implementation)
10. [Sensors & Entities](#10-sensors--entities)
11. [Diagnostics](#11-diagnostics)

---

## 1. OVERVIEW

### Purpose

The Safety Coordinator **detects and responds to environmental hazards** that threaten:
- Human life and health
- Property and structure
- Critical infrastructure

### Design Principles

| Principle | Description |
|-----------|-------------|
| **Safety First** | Life safety always takes precedence |
| **Fail Safe** | If uncertain, assume danger |
| **Immediate Response** | CRITICAL hazards trigger instant action |
| **Multi-Channel Alert** | Never rely on single notification path |
| **Override Authority** | Can override ALL other coordinators |

### What Safety Monitors

```
SAFETY COORDINATOR SCOPE
├── Fire/Smoke
│   ├── Smoke detectors
│   └── Heat anomalies
│
├── Water
│   ├── Leak sensors
│   ├── Flooding risk
│   └── (Future: Auto shutoff valve)
│
├── Air Quality
│   ├── Carbon monoxide (CO)
│   ├── Carbon dioxide (CO2)
│   ├── TVOC (volatile organics)
│   └── Particulate matter
│
├── Temperature Extremes
│   ├── Freeze risk (pipes, structure)
│   ├── Heat risk (HVAC failure)
│   └── Rapid change detection
│
└── Humidity
    ├── High humidity (mold risk)
    └── Low humidity (structure damage)
```

---

## 2. HAZARD TYPES

```python
class HazardType(Enum):
    """Types of environmental hazards."""
    
    SMOKE = "smoke"
    FIRE = "fire"
    WATER_LEAK = "water_leak"
    FLOODING = "flooding"
    CARBON_MONOXIDE = "carbon_monoxide"
    HIGH_CO2 = "high_co2"
    HIGH_TVOC = "high_tvoc"
    FREEZE_RISK = "freeze_risk"
    OVERHEAT = "overheat"
    HVAC_FAILURE = "hvac_failure"
    HIGH_HUMIDITY = "high_humidity"
    LOW_HUMIDITY = "low_humidity"
```

### Hazard Priority

| Priority | Hazard Types | Response Time |
|----------|--------------|---------------|
| **CRITICAL** | Smoke, Fire, CO | Immediate (<5s) |
| **HIGH** | Water leak, Freeze risk | Fast (<30s) |
| **MEDIUM** | High CO2, TVOC, Humidity | Prompt (<5min) |
| **LOW** | Humidity drift, Mild temp | Advisory |

---

## 3. SEVERITY FRAMEWORK

```python
class Severity(Enum):
    CRITICAL = 4  # Immediate threat to life
    HIGH = 3      # Significant threat requiring prompt action
    MEDIUM = 2    # Important but not immediately dangerous
    LOW = 1       # Advisory only

# Thresholds for numeric sensors
THRESHOLDS = {
    HazardType.CARBON_MONOXIDE: {  # ppm
        Severity.CRITICAL: 100,
        Severity.HIGH: 50,
        Severity.MEDIUM: 35,
        Severity.LOW: 10,
    },
    HazardType.HIGH_CO2: {  # ppm
        Severity.HIGH: 2500,
        Severity.MEDIUM: 1500,
        Severity.LOW: 1000,
    },
    HazardType.FREEZE_RISK: {  # °F (lower is worse)
        Severity.HIGH: 35,
        Severity.MEDIUM: 40,
        Severity.LOW: 45,
    },
    HazardType.HIGH_HUMIDITY: {  # %
        Severity.HIGH: 80,
        Severity.MEDIUM: 70,
        Severity.LOW: 60,
    },
}
```

---

## 4. SENSOR REQUIREMENTS

### Required (Minimum)

| Type | Pattern | Purpose |
|------|---------|---------|
| Smoke | `binary_sensor.*smoke*` | Fire detection |
| CO | `sensor.*carbon_monoxide*` | CO poisoning |
| Water Leak | `binary_sensor.*leak*` | Leak detection |

### Recommended

| Type | Pattern | Purpose |
|------|---------|---------|
| CO2 | `sensor.*co2*` | Air quality |
| TVOC | `sensor.*tvoc*` | Air quality |
| Temperature | `sensor.*temperature*` | Freeze/heat |
| Humidity | `sensor.*humidity*` | Structure protection |

### Future Affordance: Water Shutoff

```python
# Design accommodates future water shutoff valve
WATER_SHUTOFF_ENTITY = "valve.main_water"  # Moen Flo, Phyn, etc.

async def _water_leak_response(self, hazard: Hazard) -> list[CoordinatorAction]:
    actions = []
    
    # If shutoff valve exists, close it
    if self._has_water_shutoff():
        actions.append(ServiceCallAction(
            coordinator="safety",
            action_type="water_shutoff",
            severity=Severity.HIGH,
            confidence=hazard.confidence,
            reason="Water leak - shutting off main",
            domain="valve",
            service="close",
            service_data={"entity_id": WATER_SHUTOFF_ENTITY},
        ))
    
    return actions
```

---

## 5. DETECTION LOGIC

### Binary Sensors (Smoke, Leak)

```python
async def _handle_binary_hazard(
    self, 
    entity_id: str, 
    new_state: str,
    hazard_type: HazardType,
) -> Hazard | None:
    
    if new_state != "on":
        # Hazard cleared
        await self.clear_hazard(hazard_type, self._get_location(entity_id))
        return None
    
    location = self._get_sensor_location(entity_id)
    
    if hazard_type == HazardType.SMOKE:
        severity = Severity.CRITICAL
        message = f"🚨 SMOKE DETECTED in {location}!"
    elif hazard_type == HazardType.WATER_LEAK:
        severity = Severity.HIGH
        message = f"💧 Water leak detected in {location}!"
    else:
        severity = Severity.HIGH
        message = f"Hazard: {hazard_type.value} in {location}"
    
    return Hazard(
        type=hazard_type,
        severity=severity,
        confidence=0.95,
        location=location,
        sensor_id=entity_id,
        value="on",
        threshold="on",
        detected_at=datetime.now(),
        message=message,
    )
```

### Numeric Sensors (CO, Temp, Humidity)

```python
async def _handle_numeric_hazard(
    self,
    entity_id: str,
    value: float,
    hazard_type: HazardType,
) -> Hazard | None:
    
    severity = self._classify_severity(hazard_type, value)
    
    if severity is None:
        return None  # Below all thresholds
    
    location = self._get_sensor_location(entity_id)
    threshold = self._get_threshold(hazard_type, severity)
    
    messages = {
        HazardType.CARBON_MONOXIDE: f"⚠️ CO {value} ppm in {location}",
        HazardType.HIGH_CO2: f"🌬️ High CO2 ({value} ppm) in {location}",
        HazardType.FREEZE_RISK: f"❄️ Freeze risk: {value}°F in {location}",
        HazardType.HIGH_HUMIDITY: f"💦 High humidity: {value}% in {location}",
    }
    
    return Hazard(
        type=hazard_type,
        severity=severity,
        confidence=0.85,
        location=location,
        sensor_id=entity_id,
        value=value,
        threshold=threshold,
        detected_at=datetime.now(),
        message=messages.get(hazard_type, f"{hazard_type.value}: {value}"),
    )
```

### Rate of Change Detection

```python
class RateOfChangeDetector:
    """Detect rapid changes indicating problems."""
    
    THRESHOLDS = {
        "temperature_drop": {"rate": -5.0, "hazard": HazardType.HVAC_FAILURE},
        "temperature_rise": {"rate": 5.0, "hazard": HazardType.HVAC_FAILURE},
        "humidity_spike": {"rate": 20.0, "hazard": HazardType.WATER_LEAK},
    }
    
    # Monitors sensor history and detects rapid changes
    # Triggers MEDIUM severity alerts for investigation
```

---

## 6. RESPONSE ACTIONS

### Action Matrix

| Hazard | Severity | Automatic Actions |
|--------|----------|-------------------|
| Smoke/Fire | CRITICAL | All lights 100%, notify all channels |
| CO | CRITICAL | Lights on, ventilation max, notify all |
| Water Leak | HIGH | Notify, (future: shutoff valve) |
| Freeze Risk | HIGH | Override HVAC to heat, notify |
| High CO2 | MEDIUM | Request ventilation, notify |
| High Humidity | MEDIUM | Signal dehumidifier, notify |

### Response Implementation

```python
async def _critical_response(self, hazard: Hazard) -> list[CoordinatorAction]:
    """CRITICAL severity: Maximum response."""
    actions = []
    
    # All lights ON at full brightness
    actions.append(ServiceCallAction(
        coordinator="safety",
        action_type="emergency_lights",
        severity=Severity.CRITICAL,
        confidence=hazard.confidence,
        reason=hazard.message,
        domain="light",
        service="turn_on",
        service_data={"entity_id": "all", "brightness": 255},
    ))
    
    # CO-specific: Maximize ventilation
    if hazard.type == HazardType.CARBON_MONOXIDE:
        actions.append(ServiceCallAction(
            coordinator="safety",
            action_type="emergency_ventilate",
            severity=Severity.CRITICAL,
            confidence=hazard.confidence,
            reason="CO detected - maximizing ventilation",
            domain="fan",
            service="turn_on",
            service_data={"entity_id": "all"},
        ))
    
    return actions


async def _high_response(self, hazard: Hazard) -> list[CoordinatorAction]:
    """HIGH severity: Urgent response."""
    actions = []
    
    # Freeze risk: Override HVAC
    if hazard.type == HazardType.FREEZE_RISK:
        actions.append(ConstraintAction(
            coordinator="safety",
            action_type="freeze_protection",
            severity=Severity.HIGH,
            confidence=hazard.confidence,
            reason="Freeze risk - forcing heat",
            constraint_type="hvac",
            constraint_data={"mode": "heat", "min_temp": 55},
        ))
    
    return actions
```

---

## 7. NOTIFICATION STRATEGY

### Channel Selection by Severity

| Severity | Channels | Quiet Hours |
|----------|----------|-------------|
| CRITICAL | iMessage + Speaker + Lights | Override |
| HIGH | iMessage + Speaker | Override |
| MEDIUM | iMessage | Respect |
| LOW | Log only | N/A |

### Light Patterns

```python
LIGHT_PATTERNS = {
    "fire": {
        "color": (255, 100, 0),  # Orange
        "effect": "flash",
        "interval_ms": 250,
    },
    "water_leak": {
        "color": (0, 0, 255),    # Blue
        "effect": "pulse",
    },
    "warning": {
        "color": (255, 255, 0),  # Yellow
        "effect": "pulse",
    },
}
```

### Alert Deduplication

```python
# Prevent alert fatigue
SUPPRESSION_WINDOWS = {
    Severity.CRITICAL: timedelta(minutes=1),   # Repeat often
    Severity.HIGH: timedelta(minutes=5),
    Severity.MEDIUM: timedelta(minutes=15),
    Severity.LOW: timedelta(hours=1),
}
```

---

## 8. OVERRIDE AUTHORITY

### Priority: 100 (Highest)

Safety can override ALL other coordinators.

```python
# Example: Freeze protection overrides Energy's peak TOU coast

safety_action = ConstraintAction(
    coordinator="safety",
    action_type="freeze_protection",
    severity=Severity.HIGH,  # 0.75 multiplier
    confidence=0.90,
)
# Effective: 100 * 0.75 * 0.95 = 71.25

energy_action = ServiceCallAction(
    coordinator="energy", 
    action_type="coast_hvac",
    severity=Severity.MEDIUM,  # 0.5 multiplier
    confidence=0.95,
)
# Effective: 40 * 0.5 * 0.975 = 19.5

# Safety wins: 71.25 >> 19.5
```

---

## 9. IMPLEMENTATION

```python
class SafetyCoordinator(BaseCoordinator):
    """Environmental hazard detection and response."""
    
    COORDINATOR_ID = "safety"
    PRIORITY = 100
    
    def __init__(self, hass: HomeAssistant, manager: CoordinatorManager):
        super().__init__(hass, manager)
        self._active_hazards: dict[str, Hazard] = {}
        self._deduplicator = AlertDeduplicator()
        self._rate_detector = RateOfChangeDetector()
    
    async def async_setup(self) -> None:
        # Discover and register all safety sensors
        # Binary: smoke, leak
        # Numeric: CO, CO2, temp, humidity
        pass
    
    async def evaluate(
        self,
        intents: list[Intent],
        context: CoordinatorContext,
    ) -> list[CoordinatorAction]:
        actions = []
        
        for intent in intents:
            hazard = await self._process_intent(intent)
            if hazard:
                response = await self._respond_to_hazard(hazard)
                actions.extend(response.actions)
        
        return actions
    
    async def _respond_to_hazard(self, hazard: Hazard) -> SafetyResponse:
        # Track hazard
        self._active_hazards[f"{hazard.type}:{hazard.location}"] = hazard
        
        # Generate response based on severity
        if hazard.severity == Severity.CRITICAL:
            actions = await self._critical_response(hazard)
        elif hazard.severity == Severity.HIGH:
            actions = await self._high_response(hazard)
        else:
            actions = await self._medium_response(hazard)
        
        # Send notifications (if not deduplicated)
        if self._deduplicator.should_alert(hazard):
            await self._send_notifications(hazard)
        
        return SafetyResponse(hazard=hazard, actions=actions)
```

---

## 10. SENSORS & ENTITIES

```yaml
sensor.ura_safety_status:
  state: "normal"  # warning, alert, critical
  attributes:
    active_hazards: 0
    sensors_monitored: 15
    last_check: "2026-01-24T19:45:00"

binary_sensor.ura_safety_alert:
  state: "off"
  device_class: safety
  attributes:
    hazard_type: null
    location: null
    severity: null
```

---

## 11. DIAGNOSTICS

```yaml
sensor.ura_safety_diagnostics:
  state: "healthy"
  attributes:
    sensors_total: 15
    sensors_available: 15
    hazards_detected_24h: 2
    alerts_sent_24h: 3
    false_positive_rate_7d: 0.02
```

### Test Mode

```python
# Service: ura.test_safety_hazard
async def test_hazard(self, hazard_type: str, location: str, severity: str):
    """Trigger test hazard for notification testing."""
    pass
```

---

## KEY DESIGN QUESTIONS

### Q1: Water Shutoff Valve

**Question:** Do you have or plan to add a water shutoff valve (Moen Flo, Phyn)?

**Design Affordance:** Ready for `valve.main_water` entity.

**Policy Questions:**
- Auto-shutoff on leak detection?
- Require manual confirmation?
- Auto-reopen policy?

---

### Q2: Smoke Detector Integration

**Question:** What smoke detectors are integrated with HA?

**Options:**
1. Smart detectors (Nest Protect) → Full room-level detection
2. Interconnected with listener → Knows alarm triggered, not which room
3. No integration → Safety can't respond to fire

---

### Q3: Emergency Lighting

**Question:** Preferred behavior for CRITICAL hazards?

**Current Design:** All lights 100% (aids evacuation)

**Alternatives:**
- Only affected area + egress paths
- Flash pattern vs solid
- Specific colors by hazard type

---

**Document Status:** Design Complete - Pending Answers  
**Override Authority:** Can override all other coordinators

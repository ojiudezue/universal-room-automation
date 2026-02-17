# HVAC COORDINATOR DESIGN

**Version:** 1.0  
**Parent Document:** ENERGY_COORDINATOR_DESIGN.md  
**Status:** Design Complete  
**Last Updated:** 2026-01-24

---

## TABLE OF CONTENTS

1. [Overview](#1-overview)
2. [Hardware: Carrier Infinity System](#2-hardware-carrier-infinity-system)
3. [Zone-to-Room Mapping](#3-zone-to-room-mapping)
4. [Control Strategy](#4-control-strategy)
5. [Room Condition Aggregation](#5-room-condition-aggregation)
6. [Fan Coordination](#6-fan-coordination)
7. [Energy Constraint Response](#7-energy-constraint-response)
8. [Core Implementation](#8-core-implementation)
9. [Sensors & Entities](#9-sensors--entities)
10. [Configuration Options](#10-configuration-options)
11. [Integration Points](#11-integration-points)

---

## 1. OVERVIEW

### Purpose

The HVAC Coordinator is a **domain coordinator** within URA that:

1. **Manages** the 3 Carrier Infinity HVAC zones directly
2. **Responds** to constraints from Energy Coordinator
3. **Aggregates** room conditions from many URA rooms → fewer HVAC zones
4. **Coordinates** room fans based on temperature/humidity conditions
5. **Chooses** between coarse control (presets) and fine control (setpoints)

### Relationship to Energy Coordinator

```
┌─────────────────────────────────────────────────────────────────┐
│                     ENERGY COORDINATOR                          │
│                   (Active Controller + Governor)                │
│                                                                 │
│  Publishes: energy.hvac_constraint events                      │
│  Contains:  TOU awareness, battery strategy, load priorities   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HVACConstraints:
                              │ • mode: normal|pre_cool|coast|shed
                              │ • setpoint_offset: -3 to +4°F
                              │ • occupied_only: bool
                              │ • max_runtime_minutes: int|null
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      HVAC COORDINATOR                           │
│                   (Zone Manager + Fan Control)                  │
│                                                                 │
│  Manages:   3 Carrier Infinity zones                           │
│  Aggregates: Room conditions → zone decisions                  │
│  Coordinates: 20 room fans                                     │
│  Protects:  Sleep hours, comfort bounds                        │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │  ZONE 1  │   │  ZONE 2  │   │  ZONE 3  │
        │  Master  │   │ Upstairs │   │   Main   │
        │  Suite   │   │          │   │  Living  │
        └──────────┘   └──────────┘   └──────────┘
```

### Design Philosophy

1. **Coarse control for mode changes** - Use Carrier presets (away/home/sleep)
2. **Fine control for energy optimization** - Adjust setpoints within modes
3. **Aggregate up, apply down** - Many rooms inform few zone decisions
4. **Sleep protection** - Limited offsets during sleep hours
5. **Fans supplement HVAC** - Use room fans during energy-constrained periods
6. **User overrides respected** - `preset_mode: manual` means hands off

---

## 2. HARDWARE: CARRIER INFINITY SYSTEM

### Active HVAC Zones

| Zone | Entity ID | Physical Location | Serves |
|------|-----------|-------------------|--------|
| **Zone 1** | `climate.thermostat_bryant_wifi_studyb_zone_1` | Study B (1st floor) | Master Suite |
| **Zone 2** | `climate.up_hallway_zone_2` | Up Hallway (2nd floor) | Upstairs bedrooms, game room |
| **Zone 3** | `climate.back_hallway_zone_3` | Back Hallway (1st floor) | Main living areas |

**Note:** `climate.master_suite_zone_1` is a derived sensor and should be ignored.

### Control Capabilities

```yaml
# Per-zone capabilities (all 3 zones identical)
hvac_modes:
  - "off"        # System off
  - "fan_only"   # Fan circulation only
  - "heat_cool"  # Auto mode (heating or cooling as needed)
  - "heat"       # Heating only
  - "cool"       # Cooling only

fan_modes:
  - "low"
  - "med"
  - "high"
  - "auto"       # System controlled

preset_modes:
  - "away"       # Wide temperature band, minimal conditioning
  - "home"       # Normal comfort band
  - "sleep"      # Optimized for sleeping
  - "wake"       # Transition to active comfort
  - "vacation"   # Extended absence
  - "manual"     # USER OVERRIDE - do not touch!
  - "resume"     # Return to scheduled programming

temperature_control:
  min_temp: 45°F
  max_temp: 95°F
  step: 1°F
  target_temp_high: # Cooling setpoint
  target_temp_low:  # Heating setpoint
```

### Monitoring Attributes (Read-Only)

```yaml
# Available from each zone entity
current_temperature: 71      # Zone thermostat reading
current_humidity: 42         # Zone humidity
hvac_action: "heating"       # Current action: idle, heating, cooling
conditioning: "active_heat"  # active_heat, active_cool, idle
blower_rpm: 915             # Fan speed feedback
status_mode: "auto"         # System status
```

### Service Calls

```python
# Set preset mode (coarse control)
await hass.services.async_call(
    "climate", "set_preset_mode",
    {"entity_id": "climate.up_hallway_zone_2", "preset_mode": "away"}
)

# Set temperature (fine control)
await hass.services.async_call(
    "climate", "set_temperature",
    {
        "entity_id": "climate.up_hallway_zone_2",
        "target_temp_high": 77,  # Cooling setpoint
        "target_temp_low": 70,   # Heating setpoint
    }
)

# Set HVAC mode
await hass.services.async_call(
    "climate", "set_hvac_mode",
    {"entity_id": "climate.up_hallway_zone_2", "hvac_mode": "cool"}
)

# Set fan mode
await hass.services.async_call(
    "climate", "set_fan_mode",
    {"entity_id": "climate.up_hallway_zone_2", "fan_mode": "high"}
)
```

---

## 3. ZONE-TO-ROOM MAPPING

### The Challenge

URA has many room zones (potentially 20+), but only 3 HVAC zones exist. Multiple URA rooms share each HVAC zone. The HVAC Coordinator must:

- Aggregate occupancy from all rooms in an HVAC zone
- Use worst-case temperature for decisions (hottest room in summer)
- Allow user configuration of room→HVAC zone mapping

### Default Zone Configuration

```python
from dataclasses import dataclass, field

@dataclass
class HVACZoneConfig:
    """Configuration for an HVAC zone and its room mappings."""
    
    zone_id: str                    # e.g., "zone_1_master"
    climate_entity: str             # e.g., "climate.thermostat_bryant_wifi_studyb_zone_1"
    friendly_name: str              # e.g., "Master Suite"
    floor: str                      # "first", "second"
    
    # Room mappings (URA room_id → weight for aggregation)
    # Weight affects how much this room influences zone decisions
    room_mappings: dict[str, float] = field(default_factory=dict)
    
    # User preferences for this zone
    user_setpoint_cool: float = 74.0  # Default cooling setpoint
    user_setpoint_heat: float = 70.0  # Default heating setpoint
    
    # Sleep hours for this zone (None if not applicable)
    sleep_schedule: tuple[int, int] | None = None  # (start_hour, end_hour)
    
    # Associated fans in rooms covered by this zone
    room_fans: list[str] = field(default_factory=list)


# Default configuration
DEFAULT_HVAC_ZONES = {
    "zone_1_master": HVACZoneConfig(
        zone_id="zone_1_master",
        climate_entity="climate.thermostat_bryant_wifi_studyb_zone_1",
        friendly_name="Master Suite",
        floor="first",
        room_mappings={
            "master_bedroom": 1.0,      # Primary room, full weight
            "master_bathroom": 0.5,     # Secondary, less influence
            "master_closet": 0.3,       # Minimal influence
        },
        user_setpoint_cool=73.0,
        user_setpoint_heat=70.0,
        sleep_schedule=(22, 7),  # 10pm - 7am
        room_fans=[
            "fan.ceilingfan_fanimaton_rf304_25_masterbedroom",
            "fan.polyfan_508s_wifi_masterbedroom",
        ],
    ),
    
    "zone_2_upstairs": HVACZoneConfig(
        zone_id="zone_2_upstairs",
        climate_entity="climate.up_hallway_zone_2",
        friendly_name="Upstairs",
        floor="second",
        room_mappings={
            "kids_bedroom_ziri": 1.0,
            "kids_bedroom_jaya": 1.0,
            "game_room": 0.8,
            "upstairs_bathroom": 0.3,
            "upstairs_hallway": 0.2,
            "exercise_room": 0.7,
        },
        user_setpoint_cool=74.0,
        user_setpoint_heat=70.0,
        sleep_schedule=(21, 7),  # 9pm - 7am (kids earlier)
        room_fans=[
            "fan.fanswitch_treat_wifi_ziribedroom",
            "fan.fanswitch_treat_wifi_jayabedroom",
            "fan.game_room_ceiling_fan",
            "fan.fan_switch_3",  # Exercise
            "fan.fan_switch_4",  # UpGuest
        ],
    ),
    
    "zone_3_main": HVACZoneConfig(
        zone_id="zone_3_main",
        climate_entity="climate.back_hallway_zone_3",
        friendly_name="Main Living",
        floor="first",
        room_mappings={
            "living_room": 1.0,
            "kitchen": 0.9,
            "dining_room": 0.8,
            "office_a": 0.9,
            "office_b": 0.9,
            "guest_bedroom": 0.7,
            "media_room": 0.8,
            "breakfast_nook": 0.6,
        },
        user_setpoint_cool=74.0,
        user_setpoint_heat=70.0,
        sleep_schedule=None,  # Main living areas, no sleep schedule
        room_fans=[
            "fan.towerfan_dreopilotmaxs_wifi_livingroom",
            "fan.polyfan_dreo704s_wifi_studya",
            "fan.media_room_ceiling_fan",
            "fan.guest_room_down_ceiling_fan",
            "fan.151732606487193_fan",  # Kitchen/Breakfast
        ],
    ),
}
```

### Room Weight Guidelines

| Weight | Meaning | Example |
|--------|---------|---------|
| **1.0** | Primary room - full influence on zone decisions | Bedrooms, living room |
| **0.7-0.9** | Secondary room - significant but not primary | Kitchen, office |
| **0.4-0.6** | Tertiary room - moderate influence | Dining room, breakfast nook |
| **0.1-0.3** | Minimal room - rarely affects decisions | Hallways, closets, bathrooms |

---

## 4. CONTROL STRATEGY

### Philosophy: Coarse vs Fine

| Control Type | Mechanism | When to Use |
|--------------|-----------|-------------|
| **Coarse** | Change `preset_mode` | Major mode changes (home→away→sleep) |
| **Fine** | Adjust `target_temp_high/low` | Energy optimization within a mode |
| **Hybrid** | Preset + temperature tuning | Normal operation with energy awareness |

### Control Strategy Enum

```python
from enum import Enum

class HVACControlStrategy(Enum):
    """Strategy for HVAC control decisions."""
    
    # COARSE CONTROL - Use presets, minimize cycling
    PRESET_BASED = "preset_based"
    # - Best for: Major occupancy changes (home→away→home)
    # - How: Change preset_mode, let thermostat manage setpoints
    # - Benefit: Thermostat's built-in schedules respected
    
    # FINE CONTROL - Direct temperature manipulation
    TEMPERATURE_BASED = "temperature_based"
    # - Best for: Energy optimization (pre-cool, coast)
    # - How: Adjust target_temp_high/low directly
    # - Benefit: Precise control of setpoint offsets
    
    # HYBRID - Preset for mode, temp for tuning
    HYBRID = "hybrid"
    # - Best for: Normal operation with energy awareness
    # - How: Set preset, then fine-tune temp within preset bounds
```

### HVAC Action Data Class

```python
@dataclass
class HVACAction:
    """An action to take on an HVAC zone."""
    
    zone_id: str
    strategy: HVACControlStrategy
    
    # Coarse control
    preset_mode: str | None = None      # away, home, sleep, etc.
    hvac_mode: str | None = None        # off, heat_cool, cool, heat
    fan_mode: str | None = None         # auto, low, med, high
    
    # Fine control
    temp_offset_cool: float | None = None  # Offset from user setpoint
    temp_offset_heat: float | None = None
    
    # Direct setpoint (overrides offset if set)
    target_temp_high: float | None = None
    target_temp_low: float | None = None
    
    # Reason for logging/debugging
    reason: str = ""
```

### Decision Matrix by Energy Mode

| Energy Mode | Strategy | Preset | Setpoint Offset | Fan | Notes |
|-------------|----------|--------|-----------------|-----|-------|
| **NORMAL** | HYBRID | home | 0 | auto | User preferences |
| **PRE_COOL** | TEMPERATURE | - | -2 to -3°F | auto | Build thermal mass |
| **PRE_HEAT** | TEMPERATURE | - | +2 to +3°F | auto | Build thermal mass |
| **COAST** | TEMPERATURE | - | +2 to +4°F | auto | Ride thermal mass |
| **SHED** | PRESET | away | - | auto | Emergency load reduction |

### Occupancy-Aware Decisions

```python
def generate_action_for_constraint(
    zone: HVACZoneConfig,
    zone_conditions: AggregatedZoneConditions,
    constraint: HVACConstraints,
) -> HVACAction:
    """Generate HVAC action considering occupancy."""
    
    # Check occupancy requirement from Energy Coordinator
    if constraint.occupied_only and not zone_conditions.any_room_occupied:
        # Zone unoccupied during energy constraint - use away preset
        return HVACAction(
            zone_id=zone.zone_id,
            strategy=HVACControlStrategy.PRESET_BASED,
            preset_mode="away",
            reason="Zone unoccupied during energy constraint",
        )
    
    # Apply constraint based on mode
    if constraint.mode == "pre_cool":
        return HVACAction(
            zone_id=zone.zone_id,
            strategy=HVACControlStrategy.TEMPERATURE_BASED,
            target_temp_high=zone.user_setpoint_cool + constraint.setpoint_offset,
            target_temp_low=zone.user_setpoint_heat,
            reason=f"Pre-cooling: {constraint.setpoint_offset}°F offset",
        )
    
    # ... other modes ...
```

---

## 5. ROOM CONDITION AGGREGATION

### Aggregated Conditions Data Class

```python
@dataclass
class AggregatedZoneConditions:
    """Aggregated conditions from all rooms in an HVAC zone."""
    
    zone_id: str
    
    # Occupancy - ANY room occupied = zone occupied
    any_room_occupied: bool
    occupied_rooms: list[str]
    total_occupancy_weight: float  # Sum of weights for occupied rooms
    
    # Temperature - use worst case for decisions
    hottest_room_temp: float
    hottest_room_id: str
    coldest_room_temp: float
    coldest_room_id: str
    weighted_avg_temp: float
    
    # Humidity - max for fan decisions
    max_humidity: float
    max_humidity_room_id: str
    weighted_avg_humidity: float
    
    # Time-based
    is_sleep_hours: bool
    predicted_occupied_soon: bool  # Based on occupancy patterns
```

### Aggregation Logic

```python
class RoomConditionAggregator:
    """Aggregate room conditions for HVAC zone decisions."""
    
    def __init__(self, hass: HomeAssistant, zone_config: HVACZoneConfig):
        self.hass = hass
        self.zone_config = zone_config
    
    async def aggregate(self) -> AggregatedZoneConditions:
        """Aggregate conditions from all rooms in this HVAC zone."""
        
        occupied_rooms = []
        temps = []
        humidities = []
        total_weight = 0.0
        
        for room_id, weight in self.zone_config.room_mappings.items():
            # Get room entity states from URA
            occ_state = self.hass.states.get(f"binary_sensor.{room_id}_occupancy")
            temp_state = self.hass.states.get(f"sensor.{room_id}_temperature")
            hum_state = self.hass.states.get(f"sensor.{room_id}_humidity")
            
            # Occupancy: ANY occupied = zone occupied
            if occ_state and occ_state.state == "on":
                occupied_rooms.append(room_id)
                total_weight += weight
            
            # Temperature with weight
            if temp_state and temp_state.state not in ("unavailable", "unknown"):
                temps.append({
                    "room_id": room_id,
                    "temp": float(temp_state.state),
                    "weight": weight,
                })
            
            # Humidity with weight
            if hum_state and hum_state.state not in ("unavailable", "unknown"):
                humidities.append({
                    "room_id": room_id,
                    "humidity": float(hum_state.state),
                    "weight": weight,
                })
        
        # Calculate aggregates
        hottest = max(temps, key=lambda x: x["temp"]) if temps else {"room_id": "", "temp": 0}
        coldest = min(temps, key=lambda x: x["temp"]) if temps else {"room_id": "", "temp": 0}
        max_hum = max(humidities, key=lambda x: x["humidity"]) if humidities else {"room_id": "", "humidity": 0}
        
        # Weighted averages
        total_temp_weight = sum(t["weight"] for t in temps)
        weighted_temp = sum(t["temp"] * t["weight"] for t in temps) / total_temp_weight if total_temp_weight else 0
        
        total_hum_weight = sum(h["weight"] for h in humidities)
        weighted_hum = sum(h["humidity"] * h["weight"] for h in humidities) / total_hum_weight if total_hum_weight else 0
        
        return AggregatedZoneConditions(
            zone_id=self.zone_config.zone_id,
            any_room_occupied=len(occupied_rooms) > 0,
            occupied_rooms=occupied_rooms,
            total_occupancy_weight=total_weight,
            hottest_room_temp=hottest["temp"],
            hottest_room_id=hottest["room_id"],
            coldest_room_temp=coldest["temp"],
            coldest_room_id=coldest["room_id"],
            weighted_avg_temp=weighted_temp,
            max_humidity=max_hum["humidity"],
            max_humidity_room_id=max_hum["room_id"],
            weighted_avg_humidity=weighted_hum,
            is_sleep_hours=self._is_sleep_hours(),
            predicted_occupied_soon=False,  # TODO: Integration with occupancy prediction
        )
    
    def _is_sleep_hours(self) -> bool:
        """Check if current time is within zone's sleep schedule."""
        if not self.zone_config.sleep_schedule:
            return False
        
        start_hour, end_hour = self.zone_config.sleep_schedule
        current_hour = dt_util.now().hour
        
        # Handle overnight schedules (e.g., 22-7)
        if start_hour > end_hour:
            return current_hour >= start_hour or current_hour < end_hour
        else:
            return start_hour <= current_hour < end_hour
```

### Worst-Case Temperature Selection

For **cooling season** (April-October in Texas):
- Use **hottest room** temperature for decisions
- If hottest room is 78°F and setpoint is 74°F, zone needs cooling

For **heating season** (November-March):
- Use **coldest room** temperature for decisions
- If coldest room is 66°F and setpoint is 70°F, zone needs heating

---

## 6. FAN COORDINATION

### Available Room Fans

| Fan Entity | Room | Type |
|------------|------|------|
| `fan.ceilingfan_fanimaton_rf304_25_masterbedroom` | Master Bedroom | Ceiling |
| `fan.polyfan_508s_wifi_masterbedroom` | Master Bedroom | Portable |
| `fan.fanswitch_treat_wifi_ziribedroom` | Ziri Bedroom | Ceiling |
| `fan.fanswitch_treat_wifi_jayabedroom` | Jaya Bedroom | Ceiling |
| `fan.game_room_ceiling_fan` | Game Room | Ceiling |
| `fan.fan_switch_3` | Exercise Room | Ceiling |
| `fan.fan_switch_4` | Up Guest | Ceiling |
| `fan.towerfan_dreopilotmaxs_wifi_livingroom` | Living Room | Tower |
| `fan.polyfan_dreo704s_wifi_studya` | Study A | Portable |
| `fan.media_room_ceiling_fan` | Media Room | Ceiling |
| `fan.guest_room_down_ceiling_fan` | Guest Bedroom | Ceiling |
| `fan.151732606487193_fan` | Kitchen/Breakfast | Portable |
| `fan.switch_shelly2pmg3_wifi_dnguestbathrooom2_humidityfan` | Guest Bath | Exhaust |
| `fan.switch_shelly1pmgen3_wifi_upguestbathroomfan` | Up Guest Bath | Exhaust |

### Fan Activation Triggers

```python
@dataclass
class FanAction:
    """Action to take on a room fan."""
    fan_entity: str
    action: str  # "turn_on", "turn_off", "set_percentage"
    percentage: int | None = None
    reason: str = ""


class FanCoordinator:
    """Coordinate room fans based on conditions and HVAC state."""
    
    # Thresholds
    HUMIDITY_HIGH = 60       # Turn on fan if humidity exceeds this
    TEMP_DELTA_THRESHOLD = 3 # Turn on fan if room is 3°F above setpoint
    
    async def evaluate_fans(
        self,
        zone_conditions: AggregatedZoneConditions,
        hvac_state: HVACZoneState,
        energy_constraint: HVACConstraints | None,
    ) -> list[FanAction]:
        """
        Evaluate and generate fan actions based on conditions.
        
        Fan activation triggers:
        1. High humidity in a room → Turn on that room's fan
        2. Room significantly warmer than setpoint → Fan for circulation
        3. HVAC in fan_only mode → Support with ceiling fans
        4. Energy coast mode → Fans help maintain comfort with less HVAC
        """
        actions = []
        
        for fan_entity in self.zone_config.room_fans:
            room_id = self._fan_to_room(fan_entity)
            if not room_id:
                continue
            
            # Get room-specific conditions
            room_temp = self._get_room_temp(room_id)
            room_humidity = self._get_room_humidity(room_id)
            room_occupied = room_id in zone_conditions.occupied_rooms
            
            # Skip if room not occupied (save energy)
            if not room_occupied:
                if self._is_fan_on(fan_entity):
                    actions.append(FanAction(
                        fan_entity=fan_entity,
                        action="turn_off",
                        reason="Room unoccupied",
                    ))
                continue
            
            should_run = False
            reason = ""
            
            # Trigger 1: High humidity
            if room_humidity and room_humidity > self.HUMIDITY_HIGH:
                should_run = True
                reason = f"High humidity ({room_humidity}%)"
            
            # Trigger 2: Room warmer than setpoint (cooling season)
            if room_temp and hvac_state.target_temp_high:
                delta = room_temp - hvac_state.target_temp_high
                if delta > self.TEMP_DELTA_THRESHOLD:
                    should_run = True
                    reason = f"Room {delta:.1f}°F above setpoint"
            
            # Trigger 3: Energy coast mode - fans help maintain comfort
            if energy_constraint and energy_constraint.mode == "coast":
                if room_temp and hvac_state.target_temp_high:
                    if room_temp > hvac_state.target_temp_high - 1:
                        should_run = True
                        reason = "Supporting coast mode with circulation"
            
            # Generate action
            is_on = self._is_fan_on(fan_entity)
            
            if should_run and not is_on:
                actions.append(FanAction(
                    fan_entity=fan_entity,
                    action="turn_on",
                    reason=reason,
                ))
            elif not should_run and is_on:
                actions.append(FanAction(
                    fan_entity=fan_entity,
                    action="turn_off",
                    reason="Conditions normalized",
                ))
        
        return actions
```

### Fan-to-Room Mapping

```python
FAN_ROOM_MAP = {
    "fan.ceilingfan_fanimaton_rf304_25_masterbedroom": "master_bedroom",
    "fan.polyfan_508s_wifi_masterbedroom": "master_bedroom",
    "fan.fanswitch_treat_wifi_ziribedroom": "kids_bedroom_ziri",
    "fan.fanswitch_treat_wifi_jayabedroom": "kids_bedroom_jaya",
    "fan.game_room_ceiling_fan": "game_room",
    "fan.fan_switch_3": "exercise_room",
    "fan.fan_switch_4": "upstairs_guest",
    "fan.towerfan_dreopilotmaxs_wifi_livingroom": "living_room",
    "fan.polyfan_dreo704s_wifi_studya": "office_a",
    "fan.media_room_ceiling_fan": "media_room",
    "fan.guest_room_down_ceiling_fan": "guest_bedroom",
    "fan.151732606487193_fan": "kitchen",
}
```

---

## 7. ENERGY CONSTRAINT RESPONSE

### HVACConstraints Data Class

```python
@dataclass
class HVACConstraints:
    """Constraints from Energy Coordinator."""
    
    mode: str                     # normal, pre_cool, pre_heat, coast, shed
    setpoint_offset: float        # °F offset from user preference
    occupied_only: bool           # Only condition occupied zones
    max_runtime_minutes: int | None  # Limit HVAC runtime during peak
    reason: str                   # Human-readable reason
    
    @classmethod
    def from_dict(cls, data: dict) -> "HVACConstraints":
        return cls(
            mode=data.get("mode", "normal"),
            setpoint_offset=data.get("setpoint_offset", 0),
            occupied_only=data.get("occupied_only", False),
            max_runtime_minutes=data.get("max_runtime_minutes"),
            reason=data.get("reason", ""),
        )
```

### Response Logic by Mode

```python
class HVACActionGenerator:
    """Generate HVAC actions based on conditions and constraints."""
    
    def generate_for_energy_constraint(
        self,
        zone: HVACZoneConfig,
        zone_state: HVACZoneState,
        constraint: HVACConstraints,
    ) -> HVACAction:
        """Generate HVAC action for energy constraint."""
        
        # SHED: Emergency - use coarse control
        if constraint.mode == "shed":
            return HVACAction(
                zone_id=zone.zone_id,
                strategy=HVACControlStrategy.PRESET_BASED,
                preset_mode="away",
                reason=f"Energy shedding: {constraint.reason}",
            )
        
        # PRE_COOL: Fine control - lower cooling setpoint
        if constraint.mode == "pre_cool":
            return HVACAction(
                zone_id=zone.zone_id,
                strategy=HVACControlStrategy.TEMPERATURE_BASED,
                target_temp_high=zone.user_setpoint_cool + constraint.setpoint_offset,
                target_temp_low=zone.user_setpoint_heat,
                reason=f"Pre-cooling: {constraint.setpoint_offset}°F offset",
            )
        
        # PRE_HEAT: Fine control - raise heating setpoint
        if constraint.mode == "pre_heat":
            return HVACAction(
                zone_id=zone.zone_id,
                strategy=HVACControlStrategy.TEMPERATURE_BASED,
                target_temp_low=zone.user_setpoint_heat + abs(constraint.setpoint_offset),
                target_temp_high=zone.user_setpoint_cool,
                reason=f"Pre-heating: {constraint.setpoint_offset}°F offset",
            )
        
        # COAST: Fine control - allow wider temperature band
        if constraint.mode == "coast":
            if zone_state.is_cooling_season:
                return HVACAction(
                    zone_id=zone.zone_id,
                    strategy=HVACControlStrategy.TEMPERATURE_BASED,
                    target_temp_high=zone.user_setpoint_cool + constraint.setpoint_offset,
                    target_temp_low=zone.user_setpoint_heat,
                    reason=f"Coasting: +{constraint.setpoint_offset}°F during peak",
                )
            else:
                return HVACAction(
                    zone_id=zone.zone_id,
                    strategy=HVACControlStrategy.TEMPERATURE_BASED,
                    target_temp_low=zone.user_setpoint_heat - abs(constraint.setpoint_offset),
                    target_temp_high=zone.user_setpoint_cool,
                    reason=f"Coasting: -{abs(constraint.setpoint_offset)}°F during peak",
                )
        
        # NORMAL: Return to user preferences
        return HVACAction(
            zone_id=zone.zone_id,
            strategy=HVACControlStrategy.HYBRID,
            preset_mode="home",
            target_temp_high=zone.user_setpoint_cool,
            target_temp_low=zone.user_setpoint_heat,
            reason="Normal operation",
        )
```

### Sleep Hour Protection

```python
def _limit_for_sleep(
    self, 
    constraint: HVACConstraints | None,
    is_sleep_hours: bool,
) -> HVACConstraints | None:
    """Limit energy constraint offsets during sleep hours."""
    if not constraint or not is_sleep_hours:
        return constraint
    
    MAX_SLEEP_OFFSET = 1.5  # Max ±1.5°F during sleep
    
    if abs(constraint.setpoint_offset) > MAX_SLEEP_OFFSET:
        limited_offset = MAX_SLEEP_OFFSET if constraint.setpoint_offset > 0 else -MAX_SLEEP_OFFSET
        return HVACConstraints(
            mode=constraint.mode,
            setpoint_offset=limited_offset,
            occupied_only=constraint.occupied_only,
            max_runtime_minutes=constraint.max_runtime_minutes,
            reason=f"{constraint.reason} (limited for sleep)",
        )
    
    return constraint
```

### Zone-by-Zone Strategy Table

| Situation | Zone 1 (Master) | Zone 2 (Upstairs) | Zone 3 (Main) |
|-----------|-----------------|-------------------|---------------|
| **NORMAL** | User pref, fan auto | User pref, fan auto | Follow schedule |
| **PRE_COOL** | -3°F, fan medium | -3°F if occupied | -2°F if occupied |
| **COAST (day)** | +3°F, fan auto | +4°F unoccupied | +3°F |
| **COAST (sleep)** | +1.5°F max | +1.5°F max | N/A |
| **SHED** | Away preset | OFF if unoccupied | Away preset |

---

## 8. CORE IMPLEMENTATION

### HVACCoordinator Class

```python
class HVACCoordinator:
    """
    HVAC zone coordination with energy awareness.
    
    Responsibilities:
    1. Manage 3 Carrier Infinity HVAC zones
    2. Respond to Energy Coordinator constraints
    3. Aggregate room conditions (many rooms → few zones)
    4. Coordinate room fans
    5. Choose between coarse (preset) and fine (temp) control
    """
    
    def __init__(
        self,
        hass: HomeAssistant,
        event_bus: DomainEventBus,
        zone_configs: dict[str, HVACZoneConfig] | None = None,
    ) -> None:
        self.hass = hass
        self.event_bus = event_bus
        
        # Zone configurations
        self.zone_configs = zone_configs or DEFAULT_HVAC_ZONES
        
        # Room aggregators per zone
        self.aggregators = {
            zone_id: RoomConditionAggregator(hass, config)
            for zone_id, config in self.zone_configs.items()
        }
        
        # Fan coordinators per zone
        self.fan_coordinators = {
            zone_id: FanCoordinator(hass, config)
            for zone_id, config in self.zone_configs.items()
        }
        
        # Current energy constraints
        self._energy_constraint: HVACConstraints | None = None
        
        # Action generator
        self._action_generator = HVACActionGenerator()
        
        # Subscribe to energy events
        self.event_bus.subscribe("energy.hvac_constraint", self._on_energy_constraint)
    
    async def async_init(self) -> None:
        """Initialize HVAC coordinator."""
        # Verify HVAC entities exist
        for zone_id, config in self.zone_configs.items():
            state = self.hass.states.get(config.climate_entity)
            if not state or state.state == "unavailable":
                _LOGGER.warning(
                    f"HVAC zone {zone_id} entity unavailable: {config.climate_entity}"
                )
        
        _LOGGER.info(f"HVAC Coordinator initialized with {len(self.zone_configs)} zones")
    
    async def _on_energy_constraint(self, event: DomainEvent) -> None:
        """Handle constraint update from Energy Coordinator."""
        self._energy_constraint = HVACConstraints.from_dict(event.data)
        
        _LOGGER.info(
            f"HVAC: Received energy constraint - mode={self._energy_constraint.mode}, "
            f"offset={self._energy_constraint.setpoint_offset}°F, "
            f"reason={self._energy_constraint.reason}"
        )
        
        # Apply constraints to all zones
        await self._apply_constraints()
    
    async def _apply_constraints(self) -> None:
        """Apply current energy constraints to all HVAC zones."""
        for zone_id, config in self.zone_configs.items():
            # Get aggregated room conditions
            conditions = await self.aggregators[zone_id].aggregate()
            
            # Get current zone state
            zone_state = await self._get_zone_state(config)
            
            # Check for manual override - respect user
            if zone_state.preset_mode == "manual":
                _LOGGER.debug(f"Zone {zone_id} in manual mode - skipping")
                continue
            
            # Check occupancy requirement
            if self._energy_constraint and self._energy_constraint.occupied_only:
                if not conditions.any_room_occupied:
                    await self._execute_action(HVACAction(
                        zone_id=zone_id,
                        strategy=HVACControlStrategy.PRESET_BASED,
                        preset_mode="away",
                        reason="Zone unoccupied during energy constraint",
                    ))
                    continue
            
            # Apply sleep hour protection
            constraint = self._limit_for_sleep(
                self._energy_constraint, 
                conditions.is_sleep_hours
            )
            
            # Generate and execute action
            if constraint:
                action = self._action_generator.generate_for_energy_constraint(
                    config, zone_state, constraint
                )
                await self._execute_action(action)
            
            # Evaluate fans for this zone
            fan_actions = await self.fan_coordinators[zone_id].evaluate_fans(
                conditions, zone_state, constraint
            )
            for fan_action in fan_actions:
                await self._execute_fan_action(fan_action)
    
    async def _execute_action(self, action: HVACAction) -> None:
        """Execute an HVAC action on a zone."""
        config = self.zone_configs[action.zone_id]
        entity_id = config.climate_entity
        
        _LOGGER.debug(f"HVAC executing on {entity_id}: {action}")
        
        if action.preset_mode:
            await self.hass.services.async_call(
                "climate", "set_preset_mode",
                {"entity_id": entity_id, "preset_mode": action.preset_mode}
            )
        
        if action.hvac_mode:
            await self.hass.services.async_call(
                "climate", "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": action.hvac_mode}
            )
        
        if action.target_temp_high is not None or action.target_temp_low is not None:
            service_data = {"entity_id": entity_id}
            if action.target_temp_high is not None:
                service_data["target_temp_high"] = action.target_temp_high
            if action.target_temp_low is not None:
                service_data["target_temp_low"] = action.target_temp_low
            
            await self.hass.services.async_call(
                "climate", "set_temperature", service_data
            )
        
        if action.fan_mode:
            await self.hass.services.async_call(
                "climate", "set_fan_mode",
                {"entity_id": entity_id, "fan_mode": action.fan_mode}
            )
    
    async def _execute_fan_action(self, action: FanAction) -> None:
        """Execute a fan action."""
        _LOGGER.debug(f"Fan: {action.fan_entity} → {action.action} ({action.reason})")
        
        if action.action == "turn_on":
            await self.hass.services.async_call(
                "fan", "turn_on", {"entity_id": action.fan_entity}
            )
        elif action.action == "turn_off":
            await self.hass.services.async_call(
                "fan", "turn_off", {"entity_id": action.fan_entity}
            )
        elif action.action == "set_percentage" and action.percentage is not None:
            await self.hass.services.async_call(
                "fan", "set_percentage",
                {"entity_id": action.fan_entity, "percentage": action.percentage}
            )
    
    async def _get_zone_state(self, config: HVACZoneConfig) -> HVACZoneState:
        """Get current state of an HVAC zone."""
        state = self.hass.states.get(config.climate_entity)
        
        if not state or state.state == "unavailable":
            return HVACZoneState(zone_id=config.zone_id, available=False)
        
        attrs = state.attributes
        
        return HVACZoneState(
            zone_id=config.zone_id,
            available=True,
            hvac_mode=state.state,
            preset_mode=attrs.get("preset_mode"),
            fan_mode=attrs.get("fan_mode"),
            current_temp=attrs.get("current_temperature"),
            current_humidity=attrs.get("current_humidity"),
            target_temp_high=attrs.get("target_temp_high"),
            target_temp_low=attrs.get("target_temp_low"),
            hvac_action=attrs.get("hvac_action"),
            is_cooling_season=self._is_cooling_season(),
        )
    
    def _is_cooling_season(self) -> bool:
        """Determine if we're in cooling season (Texas)."""
        month = dt_util.now().month
        return month in [4, 5, 6, 7, 8, 9, 10]  # April - October


@dataclass
class HVACZoneState:
    """Current state of an HVAC zone."""
    zone_id: str
    available: bool = True
    hvac_mode: str | None = None
    preset_mode: str | None = None
    fan_mode: str | None = None
    current_temp: float | None = None
    current_humidity: float | None = None
    target_temp_high: float | None = None
    target_temp_low: float | None = None
    hvac_action: str | None = None
    is_cooling_season: bool = True
```

---

## 9. SENSORS & ENTITIES

### HVAC Coordinator Sensors

```yaml
# Overall HVAC mode sensor
sensor.ura_hvac_mode:
  state: "coast"  # normal, pre_cool, pre_heat, coast, shed
  attributes:
    energy_constraint_active: true
    setpoint_offset: 3.0
    constraint_reason: "Summer peak - coast mode"
    constraint_source: "energy_coordinator"

# Per-zone status sensors
sensor.ura_hvac_zone_1_status:
  state: "heat_cool"
  attributes:
    friendly_name: "Master Suite"
    zone_id: "zone_1_master"
    climate_entity: "climate.thermostat_bryant_wifi_studyb_zone_1"
    preset_mode: "home"
    effective_cool_setpoint: 77  # User 74 + 3 offset
    effective_heat_setpoint: 70
    current_temperature: 75
    current_humidity: 42
    any_room_occupied: true
    occupied_rooms: ["master_bedroom"]
    is_sleep_hours: false
    active_fans: ["fan.ceilingfan_fanimaton_rf304_25_masterbedroom"]

sensor.ura_hvac_zone_2_status:
  state: "heat_cool"
  attributes:
    friendly_name: "Upstairs"
    zone_id: "zone_2_upstairs"
    climate_entity: "climate.up_hallway_zone_2"
    preset_mode: "sleep"
    effective_cool_setpoint: 75.5  # Limited for sleep
    effective_heat_setpoint: 70
    current_temperature: 74
    current_humidity: 40
    any_room_occupied: true
    occupied_rooms: ["kids_bedroom_ziri", "kids_bedroom_jaya"]
    is_sleep_hours: true
    active_fans: []

sensor.ura_hvac_zone_3_status:
  state: "heat_cool"
  attributes:
    friendly_name: "Main Living"
    zone_id: "zone_3_main"
    climate_entity: "climate.back_hallway_zone_3"
    preset_mode: "away"  # Unoccupied during constraint
    effective_cool_setpoint: 80
    effective_heat_setpoint: 65
    current_temperature: 76
    current_humidity: 38
    any_room_occupied: false
    occupied_rooms: []
    is_sleep_hours: false
    active_fans: []

# Compliance sensor
binary_sensor.ura_hvac_energy_constrained:
  state: "on"
  attributes:
    constraint_mode: "coast"
    constraint_source: "energy_coordinator"
    zones_affected: ["zone_1_master", "zone_2_upstairs", "zone_3_main"]
    compliance_rate: 0.67
```

### Diagnostic Sensors

```yaml
sensor.hvac_coordinator_compliance:
  state: "partial"  # full, partial, overridden
  attributes:
    zones_compliant: ["zone_2_upstairs"]
    zones_overridden: ["zone_1_master", "zone_3_main"]
    compliance_rate_today: 0.67
    override_details:
      zone_1_master:
        expected_setpoint: 77
        actual_setpoint: 73
        override_duration_minutes: 35
        likely_source: "thermostat_manual"

sensor.hvac_coordinator_effectiveness:
  state: "fair"
  attributes:
    energy_saved_vs_baseline_kwh: 2.1
    comfort_violations: 2
    pre_cool_effectiveness: 0.78
    coast_compliance_rate: 0.45
    fan_assist_activations: 8
```

---

## 10. CONFIGURATION OPTIONS

### Options Flow Schema

```python
# config_flow.py

HVAC_OPTIONS_SCHEMA = vol.Schema({
    # Per-zone configuration
    vol.Optional("zone_1_cool_setpoint", default=74): vol.Coerce(float),
    vol.Optional("zone_1_heat_setpoint", default=70): vol.Coerce(float),
    vol.Optional("zone_1_sleep_start", default=22): vol.All(int, vol.Range(0, 23)),
    vol.Optional("zone_1_sleep_end", default=7): vol.All(int, vol.Range(0, 23)),
    
    vol.Optional("zone_2_cool_setpoint", default=74): vol.Coerce(float),
    vol.Optional("zone_2_heat_setpoint", default=70): vol.Coerce(float),
    vol.Optional("zone_2_sleep_start", default=21): vol.All(int, vol.Range(0, 23)),
    vol.Optional("zone_2_sleep_end", default=7): vol.All(int, vol.Range(0, 23)),
    
    vol.Optional("zone_3_cool_setpoint", default=74): vol.Coerce(float),
    vol.Optional("zone_3_heat_setpoint", default=70): vol.Coerce(float),
    
    # Global settings
    vol.Optional("max_sleep_offset", default=1.5): vol.Coerce(float),
    vol.Optional("fan_humidity_threshold", default=60): vol.All(int, vol.Range(40, 80)),
    vol.Optional("fan_temp_delta_threshold", default=3.0): vol.Coerce(float),
})
```

### Room-to-Zone Mapping Configuration

```yaml
# Example configuration in options
hvac_zone_mapping:
  zone_1_master:
    rooms:
      - room_id: master_bedroom
        weight: 1.0
      - room_id: master_bathroom
        weight: 0.5
      - room_id: master_closet
        weight: 0.3
    fans:
      - fan.ceilingfan_fanimaton_rf304_25_masterbedroom
      - fan.polyfan_508s_wifi_masterbedroom
```

---

## 11. INTEGRATION POINTS

### Event Bus Subscriptions

```python
# Events HVAC Coordinator listens to
"energy.hvac_constraint"     # From Energy Coordinator
"room.occupancy_changed"     # From Room entities (for quick response)
"room.temperature_changed"   # From Room entities (for monitoring)
```

### Event Bus Publications

```python
# Events HVAC Coordinator publishes
"hvac.zone_action_executed"  # When an action is taken
"hvac.fan_action_executed"   # When a fan is controlled
"hvac.override_detected"     # When user override is detected
"hvac.constraint_applied"    # When energy constraint is applied
```

### URA Room Integration

The HVAC Coordinator reads from URA room entities:

```python
# Room entities used for aggregation
binary_sensor.{room_id}_occupancy  # Occupancy state
sensor.{room_id}_temperature       # Room temperature
sensor.{room_id}_humidity          # Room humidity
```

### Energy Coordinator Integration

```python
# Constraint event payload from Energy Coordinator
{
    "mode": "coast",           # normal, pre_cool, pre_heat, coast, shed
    "setpoint_offset": 3.0,    # °F offset
    "occupied_only": true,     # Only condition occupied zones
    "max_runtime_minutes": 15, # Optional runtime limit
    "reason": "Peak TOU period - coast mode",
}
```

---

## APPENDIX: QUICK REFERENCE

### Entity IDs

| Zone | Climate Entity | Friendly Name |
|------|----------------|---------------|
| Zone 1 | `climate.thermostat_bryant_wifi_studyb_zone_1` | Master Suite |
| Zone 2 | `climate.up_hallway_zone_2` | Upstairs |
| Zone 3 | `climate.back_hallway_zone_3` | Main Living |

### Energy Mode → HVAC Response

| Energy Mode | HVAC Action | Setpoint Change | Fan Action |
|-------------|-------------|-----------------|------------|
| NORMAL | preset: home | User preference | Auto |
| PRE_COOL | temp adjust | -2 to -3°F | Auto |
| COAST | temp adjust | +2 to +4°F | Assist if needed |
| SHED | preset: away | Wide band | Off |

### Comfort Bounds

| Condition | Cooling Max | Heating Min | Notes |
|-----------|-------------|-------------|-------|
| Occupied | 78°F | 65°F | Hard limits |
| Sleep | +1.5°F max offset | -1.5°F max offset | Protection |
| Unoccupied | 82°F | 60°F | Away mode |

---

**Document Status:** Design Complete  
**Parent Document:** ENERGY_COORDINATOR_DESIGN.md  
**Implementation:** Part of URA Domain Coordinators

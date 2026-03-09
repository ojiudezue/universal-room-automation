# PLANNING v3.6.0 - Domain Coordinators

**Version:** 3.6.0  
**Codename:** "Whole-House Intelligence"  
**Status:** Planning Phase  
**Estimated Effort:** 15-20 hours  
**Priority:** HIGH (System-level optimization)  
**Prerequisites:** v3.4.0 deployed  
**Target:** Q3 2026  
**Recommended Model:** Opus 4.5 (complex architecture)

---

## 🎯 VISION

Implement **whole-house intelligence layers** that coordinate across rooms to optimize security, energy, comfort, and HVAC operations. Domain coordinators operate above individual room automation, making system-wide decisions that individual rooms cannot.

**Current limitation:**
- Each room optimizes itself independently
- No cross-room conflict resolution
- No whole-house energy management
- No coordinated security response
- HVAC zones compete for resources

**With domain coordinators:**
- Security coordinator detects whole-house anomalies
- Energy coordinator optimizes solar/battery/grid usage
- Comfort coordinator balances house-wide comfort vs efficiency
- HVAC coordinator prevents heat call conflicts
- Cross-domain optimization (security trumps comfort, etc.)

---

## 🏗️ ARCHITECTURE OVERVIEW

### Three-Layer Intelligence

```
Layer 3: Domain Coordinators (NEW - v3.6.0)
├── Security Coordinator    → Whole-house security intelligence
├── Energy Coordinator      → Solar/battery/grid optimization
├── Comfort Coordinator     → Multi-factor comfort optimization
└── HVAC Coordinator        → Zone coordination & conflict resolution
    ↓
    Cross-domain communication & priority resolution
    ↓
Layer 2: Zone Aggregation (v3.2.9)
├── Zone sensors
├── Zone automation
└── Zone-level decisions
    ↓
Layer 1: Room Automation (v3.0+)
├── Individual room decisions
├── Occupancy detection
└── Local optimization
```

### Domain Coordinator Responsibilities

**Security Coordinator:**
- Anomaly detection (unusual patterns)
- Security mode state machine (Home/Away/Night/Vacation)
- Perimeter monitoring (doors/windows)
- Alert prioritization and routing
- Camera activation triggers
- Lock coordination

**Energy Coordinator:**
- Solar production forecasting integration
- Battery charge/discharge optimization
- Grid export/import decisions
- Load shedding priority system
- TOU (Time of Use) rate awareness
- Peak demand management
- Circuit-level monitoring integration

**Comfort Coordinator:**
- Multi-factor comfort scoring (temp, humidity, air quality)
- Room-by-room comfort prioritization
- Energy vs comfort tradeoffs
- Whole-house air quality management
- Bottleneck identification (which room needs help most)
- Seasonal adaptation

**HVAC Coordinator:**
- Heat call conflict resolution (prevent simultaneous calls)
- Staggered heat call management
- Outside air damper control
- Zone balancing (prevent fighting)
- Efficiency optimization
- Preventive maintenance scheduling

---

## 📐 DETAILED DESIGN

### 1. Security Coordinator

**Purpose:** Detect anomalies, manage security modes, coordinate response.

#### State Machine

```python
class SecurityMode(Enum):
    """Security modes for whole-house security."""
    HOME = "home"           # Someone home, normal operation
    AWAY = "away"           # Nobody home, heightened security
    NIGHT = "night"         # Sleeping, perimeter monitoring
    VACATION = "vacation"   # Extended absence, strict monitoring
    ALERT = "alert"         # Security event detected
```

#### Architecture

```python
# domain_coordinators/security.py

class SecurityCoordinator:
    """
    Whole-house security intelligence.
    
    Responsibilities:
    - Detect security mode transitions
    - Monitor perimeter (doors/windows)
    - Detect anomalies (unusual activity)
    - Coordinate camera activation
    - Prioritize and route alerts
    """
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize security coordinator."""
        self.hass = hass
        self.current_mode = SecurityMode.HOME
        
        # Track perimeter state
        self.perimeter_sensors: List[str] = []
        self.interior_motion: List[str] = []
        
        # Anomaly detection state
        self.baseline_patterns: Dict[str, Any] = {}
        self.recent_events: List[SecurityEvent] = []
        
        # Alert routing
        self.alert_priorities = {
            "critical": ["pushover", "sms"],
            "high": ["pushover"],
            "medium": ["persistent_notification"],
            "low": ["logbook"]
        }
    
    async def async_init(self) -> None:
        """Initialize coordinator with entity discovery."""
        # Discover all door/window sensors
        self.perimeter_sensors = await self._discover_perimeter_sensors()
        
        # Discover all motion sensors
        self.interior_motion = await self._discover_motion_sensors()
        
        # Load baseline patterns from database
        self.baseline_patterns = await self._load_baseline_patterns()
        
        # Subscribe to relevant events
        self._subscribe_to_events()
    
    async def _discover_perimeter_sensors(self) -> List[str]:
        """Discover door and window sensors."""
        sensors = []
        
        # Get all binary sensors
        states = self.hass.states.async_all("binary_sensor")
        
        for state in states:
            device_class = state.attributes.get("device_class")
            
            if device_class in ["door", "window", "garage_door"]:
                sensors.append(state.entity_id)
        
        _LOGGER.info(f"Security: Discovered {len(sensors)} perimeter sensors")
        return sensors
    
    async def determine_security_mode(self) -> SecurityMode:
        """
        Determine appropriate security mode.
        
        Logic:
        1. Check if anyone home (person tracking)
        2. Check time of day
        3. Check manual overrides
        4. Return appropriate mode
        """
        # Get all person locations
        person_coordinator = self.hass.data[DOMAIN].get("person_coordinator")
        
        if not person_coordinator:
            return SecurityMode.HOME
        
        # Check if anyone home
        anyone_home = False
        for person_id in person_coordinator.persons:
            location = person_coordinator.get_person_location(person_id)
            if location and location != "away":
                anyone_home = True
                break
        
        if not anyone_home:
            # Nobody home - check vacation mode
            vacation_mode = self.hass.states.get("input_boolean.vacation_mode")
            if vacation_mode and vacation_mode.state == "on":
                return SecurityMode.VACATION
            else:
                return SecurityMode.AWAY
        
        # Someone home - check if night
        now = dt_util.now()
        current_time = now.time()
        
        night_start = time(22, 0)  # 10 PM
        night_end = time(6, 0)     # 6 AM
        
        if current_time >= night_start or current_time <= night_end:
            return SecurityMode.NIGHT
        else:
            return SecurityMode.HOME
    
    async def detect_anomaly(self) -> Optional[SecurityAnomaly]:
        """
        Detect security anomalies.
        
        Anomalies:
        1. Door/window opened when nobody home
        2. Motion detected in unusual location at unusual time
        3. Multiple perimeter breaches in short time
        4. Activity pattern drastically different from baseline
        
        Returns:
            SecurityAnomaly if detected, None otherwise
        """
        current_mode = await self.determine_security_mode()
        
        # Check perimeter when away
        if current_mode in [SecurityMode.AWAY, SecurityMode.VACATION]:
            for sensor in self.perimeter_sensors:
                state = self.hass.states.get(sensor)
                
                if state and state.state == "on":
                    # Perimeter breach while away
                    return SecurityAnomaly(
                        severity="critical",
                        type="perimeter_breach_away",
                        entity_id=sensor,
                        message=f"{state.attributes.get('friendly_name', sensor)} opened while away",
                        timestamp=dt_util.now()
                    )
        
        # Check unusual motion at night
        if current_mode == SecurityMode.NIGHT:
            # Check for motion in rooms that shouldn't have activity
            unusual_rooms = ["garage", "office", "basement"]
            
            for room in unusual_rooms:
                motion_sensor = f"binary_sensor.{room}_occupancy"
                state = self.hass.states.get(motion_sensor)
                
                if state and state.state == "on":
                    return SecurityAnomaly(
                        severity="high",
                        type="unusual_motion_night",
                        entity_id=motion_sensor,
                        message=f"Motion detected in {room} at night",
                        timestamp=dt_util.now()
                    )
        
        # Check multiple perimeter breaches
        recent_breaches = [
            event for event in self.recent_events
            if event.type == "perimeter_breach"
            and (dt_util.now() - event.timestamp).seconds < 300  # 5 minutes
        ]
        
        if len(recent_breaches) >= 3:
            return SecurityAnomaly(
                severity="critical",
                type="multiple_breaches",
                message=f"{len(recent_breaches)} perimeter breaches in 5 minutes",
                timestamp=dt_util.now()
            )
        
        return None
    
    async def handle_anomaly(self, anomaly: SecurityAnomaly) -> None:
        """
        Handle detected security anomaly.
        
        Actions:
        1. Log to database
        2. Send alerts based on severity
        3. Activate cameras
        4. Update security mode if needed
        5. Trigger automations
        """
        # Log to database
        await self._log_anomaly(anomaly)
        
        # Send alerts
        await self._send_alert(anomaly)
        
        # Activate cameras
        if anomaly.severity in ["critical", "high"]:
            await self._activate_cameras(anomaly)
        
        # Update mode to alert if critical
        if anomaly.severity == "critical":
            self.current_mode = SecurityMode.ALERT
            
            # Trigger alert mode automation
            await self.hass.services.async_call(
                "automation",
                "trigger",
                {"entity_id": "automation.security_alert_mode"}
            )
    
    async def _send_alert(self, anomaly: SecurityAnomaly) -> None:
        """Send security alert via appropriate channels."""
        channels = self.alert_priorities.get(anomaly.severity, ["logbook"])
        
        message = f"🚨 SECURITY ALERT: {anomaly.message}"
        
        for channel in channels:
            if channel == "pushover":
                await self.hass.services.async_call(
                    "notify",
                    "MadroneHAPushover",
                    {
                        "message": message,
                        "title": "Security Alert",
                        "data": {
                            "priority": 1 if anomaly.severity == "critical" else 0,
                            "sound": "siren" if anomaly.severity == "critical" else "pushover"
                        }
                    }
                )
            elif channel == "persistent_notification":
                await self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "message": message,
                        "title": "Security Alert"
                    }
                )
```

#### Sensors

```python
# domain_coordinators/security_sensors.py

class SecurityModeSensor(SensorEntity):
    """Sensor: Current security mode."""
    
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["home", "away", "night", "vacation", "alert"]
    
    @property
    def native_value(self) -> str:
        """Return current security mode."""
        coordinator = self.hass.data[DOMAIN]["security_coordinator"]
        return coordinator.current_mode.value


class PerimeterStatusSensor(BinarySensorEntity):
    """Binary Sensor: Perimeter secure (all doors/windows closed)."""
    
    _attr_device_class = BinarySensorDeviceClass.SAFETY
    
    @property
    def is_on(self) -> bool:
        """Return True if perimeter is secure."""
        coordinator = self.hass.data[DOMAIN]["security_coordinator"]
        
        for sensor in coordinator.perimeter_sensors:
            state = self.hass.states.get(sensor)
            if state and state.state == "on":
                return False  # Not secure
        
        return True  # Secure


class AnomalyDetectionSensor(BinarySensorEntity):
    """Binary Sensor: Security anomaly detected."""
    
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    
    @property
    def is_on(self) -> bool:
        """Return True if anomaly detected recently."""
        coordinator = self.hass.data[DOMAIN]["security_coordinator"]
        
        # Check recent anomalies (last 5 minutes)
        recent = [
            a for a in coordinator.recent_events
            if isinstance(a, SecurityAnomaly)
            and (dt_util.now() - a.timestamp).seconds < 300
        ]
        
        return len(recent) > 0
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return anomaly details."""
        coordinator = self.hass.data[DOMAIN]["security_coordinator"]
        
        recent = [
            a for a in coordinator.recent_events
            if isinstance(a, SecurityAnomaly)
            and (dt_util.now() - a.timestamp).seconds < 300
        ]
        
        if not recent:
            return {}
        
        latest = recent[-1]
        return {
            "severity": latest.severity,
            "type": latest.type,
            "message": latest.message,
            "timestamp": latest.timestamp.isoformat()
        }
```

---

### 2. Energy Coordinator

**Purpose:** Optimize solar/battery/grid usage, manage load shedding.

**User's Hardware:**
- 24.25 kW solar array (50x QCell 485W panels)
- 8x Encharge 5P batteries (40 kWh total)
- Generac 22kW natural gas generator
- SPAN panels (circuit-level monitoring)
- Emporia Vue (grid measurement)
- Solcast (solar forecasting)

#### Architecture

```python
# domain_coordinators/energy.py

class EnergyCoordinator:
    """
    Whole-house energy optimization.
    
    Responsibilities:
    - Solar production forecasting
    - Battery charge/discharge optimization
    - Grid import/export decisions
    - Load shedding priority
    - TOU rate awareness
    - Peak demand management
    
    Hardware Integration:
    - Enphase: 8x Encharge 5P batteries (5 kWh each = 40 kWh total)
    - SPAN panels: Circuit-level monitoring
    - Emporia Vue: Grid power measurement
    - Solcast: Solar production forecasting
    """
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize energy coordinator."""
        self.hass = hass
        
        # Battery state
        self.battery_capacity_kwh = 40.0  # 8x 5 kWh
        self.battery_soc: float = 0.0     # State of charge (0-100%)
        
        # Solar state
        self.solar_production_kw: float = 0.0
        self.solar_forecast: List[SolarForecast] = []
        
        # Grid state
        self.grid_import_kw: float = 0.0
        self.grid_export_kw: float = 0.0
        
        # Load state
        self.total_load_kw: float = 0.0
        self.critical_loads: List[str] = []
        self.deferrable_loads: List[str] = []
        
        # TOU rates (Time of Use)
        self.tou_schedule = {
            "off_peak": {"hours": [(0, 6), (22, 24)], "rate": 0.12},
            "mid_peak": {"hours": [(6, 16), (21, 22)], "rate": 0.18},
            "on_peak": {"hours": [(16, 21)], "rate": 0.36}
        }
    
    async def async_init(self) -> None:
        """Initialize energy coordinator."""
        # Discover battery entities
        await self._discover_battery_entities()
        
        # Discover circuit monitoring
        await self._discover_circuits()
        
        # Load solar forecast
        await self._update_solar_forecast()
        
        # Subscribe to updates
        self._subscribe_to_updates()
    
    async def _discover_battery_entities(self) -> None:
        """Discover Enphase battery entities."""
        # Enphase creates sensors like:
        # sensor.enpower_123456_battery_1_soc
        # sensor.enpower_123456_battery_2_soc
        # ... (8 batteries total)
        
        batteries = []
        states = self.hass.states.async_all("sensor")
        
        for state in states:
            entity_id = state.entity_id
            
            if "enpower" in entity_id and "battery" in entity_id and "soc" in entity_id:
                batteries.append(entity_id)
        
        _LOGGER.info(f"Energy: Discovered {len(batteries)} battery sensors")
        
        # Also discover aggregate sensors
        self.battery_power_sensor = "sensor.enpower_123456_battery_power"
        self.battery_soc_sensor = "sensor.enpower_123456_battery_soc"
    
    async def get_current_battery_soc(self) -> float:
        """Get current battery state of charge (0-100%)."""
        state = self.hass.states.get(self.battery_soc_sensor)
        
        if state:
            try:
                return float(state.state)
            except ValueError:
                return 0.0
        
        return 0.0
    
    async def get_current_solar_production(self) -> float:
        """Get current solar production in kW."""
        # Enphase sensor: sensor.envoy_123456_current_power_production
        state = self.hass.states.get("sensor.envoy_123456_current_power_production")
        
        if state:
            try:
                watts = float(state.state)
                return watts / 1000.0  # Convert W to kW
            except ValueError:
                return 0.0
        
        return 0.0
    
    async def get_current_grid_power(self) -> tuple[float, float]:
        """
        Get current grid import/export in kW.
        
        Returns:
            (import_kw, export_kw)
        """
        # Emporia Vue sensor
        state = self.hass.states.get("sensor.emporia_vue_grid_power")
        
        if state:
            try:
                watts = float(state.state)
                
                if watts > 0:
                    # Importing from grid
                    return (watts / 1000.0, 0.0)
                else:
                    # Exporting to grid
                    return (0.0, abs(watts) / 1000.0)
            except ValueError:
                return (0.0, 0.0)
        
        return (0.0, 0.0)
    
    async def optimize_battery_strategy(self) -> BatteryStrategy:
        """
        Determine optimal battery charge/discharge strategy.
        
        Strategy:
        1. Check current TOU period
        2. Check solar forecast
        3. Check battery SOC
        4. Decide: charge, discharge, hold
        
        Logic:
        - Off-peak: Charge from grid if SOC < 80%
        - On-peak: Discharge to offset grid (if SOC > 20%)
        - Mid-peak: Hold or charge from solar
        - Always prioritize solar charging
        """
        current_period = await self._get_current_tou_period()
        soc = await self.get_current_battery_soc()
        solar_kw = await self.get_current_solar_production()
        
        # Get solar forecast for next 4 hours
        upcoming_solar = await self._get_solar_forecast_window(hours=4)
        
        if current_period == "off_peak":
            # Off-peak: Charge from grid if needed
            if soc < 80.0 and upcoming_solar < 2.0:  # Low forecast
                return BatteryStrategy(
                    mode="charge_from_grid",
                    target_soc=80.0,
                    reason="Off-peak charging, low solar forecast"
                )
            else:
                return BatteryStrategy(
                    mode="hold",
                    reason="Off-peak but sufficient SOC or good solar forecast"
                )
        
        elif current_period == "on_peak":
            # On-peak: Discharge to offset expensive grid
            if soc > 20.0:
                return BatteryStrategy(
                    mode="discharge",
                    target_soc=20.0,
                    reason="On-peak discharge to avoid expensive grid"
                )
            else:
                return BatteryStrategy(
                    mode="hold",
                    reason="On-peak but SOC too low"
                )
        
        else:  # mid_peak
            # Mid-peak: Charge from solar if available
            if solar_kw > 2.0 and soc < 95.0:
                return BatteryStrategy(
                    mode="charge_from_solar",
                    reason="Mid-peak solar charging"
                )
            else:
                return BatteryStrategy(
                    mode="hold",
                    reason="Mid-peak hold"
                )
    
    async def evaluate_load_shedding(self) -> List[LoadSheddingAction]:
        """
        Evaluate if load shedding is needed.
        
        Triggers:
        1. Grid import exceeds threshold during on-peak
        2. Battery SOC critically low
        3. Solar production insufficient
        4. Peak demand approaching limit
        
        Priority (shed in this order):
        1. HVAC setback (reduce by 2°F)
        2. Water heater (delay heating cycle)
        3. Pool pump (delay cycle)
        4. EV charging (pause)
        5. Non-critical circuits (per SPAN)
        """
        actions = []
        
        # Get current state
        grid_import, _ = await self.get_current_grid_power()
        soc = await self.get_current_battery_soc()
        period = await self._get_current_tou_period()
        
        # Check on-peak grid import
        if period == "on_peak" and grid_import > 5.0:  # 5 kW threshold
            # Shed HVAC load first
            actions.append(LoadSheddingAction(
                priority=1,
                type="hvac_setback",
                target="climate.whole_house",
                action="reduce_setpoint",
                data={"delta": -2.0},  # Reduce by 2°F
                reason=f"On-peak grid import {grid_import:.1f} kW"
            ))
        
        # Check battery critically low
        if soc < 15.0:
            # Shed non-critical loads
            actions.append(LoadSheddingAction(
                priority=2,
                type="defer_water_heater",
                target="switch.water_heater",
                action="turn_off",
                reason=f"Battery critically low: {soc:.1f}%"
            ))
        
        return actions
    
    async def execute_load_shedding(self, actions: List[LoadSheddingAction]) -> None:
        """Execute load shedding actions."""
        for action in sorted(actions, key=lambda a: a.priority):
            try:
                if action.type == "hvac_setback":
                    # Reduce HVAC setpoint
                    climate_state = self.hass.states.get(action.target)
                    if climate_state:
                        current_setpoint = climate_state.attributes.get("temperature")
                        new_setpoint = current_setpoint + action.data["delta"]
                        
                        await self.hass.services.async_call(
                            "climate",
                            "set_temperature",
                            {
                                "entity_id": action.target,
                                "temperature": new_setpoint
                            }
                        )
                        
                        _LOGGER.info(
                            f"Energy: HVAC setback {current_setpoint}°F → {new_setpoint}°F "
                            f"({action.reason})"
                        )
                
                elif action.action == "turn_off":
                    # Turn off switch
                    await self.hass.services.async_call(
                        "switch",
                        "turn_off",
                        {"entity_id": action.target}
                    )
                    
                    _LOGGER.info(
                        f"Energy: Turned off {action.target} ({action.reason})"
                    )
                
            except Exception as e:
                _LOGGER.error(f"Energy: Failed to execute {action.type}: {e}")
```

#### Sensors

```python
# domain_coordinators/energy_sensors.py

class BatteryStrategySensor(SensorEntity):
    """Sensor: Current battery strategy."""
    
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["charge_from_grid", "charge_from_solar", "discharge", "hold"]
    
    @property
    def native_value(self) -> str:
        """Return current battery strategy."""
        coordinator = self.hass.data[DOMAIN]["energy_coordinator"]
        
        # This would be updated by the coordinator's optimization loop
        return getattr(coordinator, "_current_strategy", "hold")
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return strategy details."""
        coordinator = self.hass.data[DOMAIN]["energy_coordinator"]
        strategy = getattr(coordinator, "_strategy_object", None)
        
        if strategy:
            return {
                "reason": strategy.reason,
                "target_soc": strategy.target_soc,
                "updated": dt_util.now().isoformat()
            }
        
        return {}


class CurrentTOUPeriodSensor(SensorEntity):
    """Sensor: Current time-of-use period."""
    
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["off_peak", "mid_peak", "on_peak"]
    
    @property
    def native_value(self) -> str:
        """Return current TOU period."""
        coordinator = self.hass.data[DOMAIN]["energy_coordinator"]
        
        now = dt_util.now()
        current_hour = now.hour
        
        for period, data in coordinator.tou_schedule.items():
            for start, end in data["hours"]:
                if start <= current_hour < end:
                    return period
        
        return "mid_peak"  # Default
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return rate information."""
        coordinator = self.hass.data[DOMAIN]["energy_coordinator"]
        period = self.native_value
        
        return {
            "rate": coordinator.tou_schedule[period]["rate"],
            "unit": "$/kWh"
        }


class LoadSheddingActiveSensor(BinarySensorEntity):
    """Binary Sensor: Load shedding active."""
    
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    
    @property
    def is_on(self) -> bool:
        """Return True if load shedding is active."""
        coordinator = self.hass.data[DOMAIN]["energy_coordinator"]
        return getattr(coordinator, "_load_shedding_active", False)
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return active load shedding actions."""
        coordinator = self.hass.data[DOMAIN]["energy_coordinator"]
        actions = getattr(coordinator, "_active_load_shedding", [])
        
        return {
            "active_actions": len(actions),
            "actions": [
                {
                    "type": a.type,
                    "target": a.target,
                    "reason": a.reason
                }
                for a in actions
            ]
        }
```

---

### 3. Comfort Coordinator

**Purpose:** Multi-factor comfort optimization across whole house.

#### Architecture

```python
# domain_coordinators/comfort.py

class ComfortCoordinator:
    """
    Whole-house comfort optimization.
    
    Factors:
    - Temperature (target vs actual)
    - Humidity (30-60% ideal)
    - Air quality (CO2, VOCs, PM2.5)
    - Light levels (for circadian rhythm)
    - Noise levels (optional)
    
    Outputs:
    - Per-room comfort scores (0-100)
    - Whole-house comfort score
    - Bottleneck identification (which room needs help)
    - Optimization recommendations
    """
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize comfort coordinator."""
        self.hass = hass
        
        # Comfort weights (configurable)
        self.weights = {
            "temperature": 0.40,
            "humidity": 0.25,
            "air_quality": 0.25,
            "light_level": 0.10
        }
        
        # Ideal ranges
        self.ideal_ranges = {
            "temperature": (68, 72),  # °F
            "humidity": (30, 60),     # %
            "co2": (400, 1000),       # ppm
            "pm25": (0, 12),          # µg/m³
        }
    
    async def calculate_room_comfort(self, room_name: str) -> ComfortScore:
        """
        Calculate multi-factor comfort score for a room.
        
        Returns:
            ComfortScore with overall score (0-100) and factor breakdown
        """
        # Get room coordinator
        room_coord = await self._get_room_coordinator(room_name)
        if not room_coord:
            return ComfortScore(score=50.0, factors={})
        
        factors = {}
        
        # Temperature score
        temp_sensor = room_coord.entry.data.get("temperature_sensor")
        if temp_sensor:
            temp = await self._get_sensor_value(temp_sensor)
            factors["temperature"] = self._score_temperature(temp)
        
        # Humidity score
        humidity_sensor = room_coord.entry.data.get("humidity_sensor")
        if humidity_sensor:
            humidity = await self._get_sensor_value(humidity_sensor)
            factors["humidity"] = self._score_humidity(humidity)
        
        # Air quality score
        co2_sensor = room_coord.entry.data.get("co2_sensor")
        if co2_sensor:
            co2 = await self._get_sensor_value(co2_sensor)
            factors["air_quality"] = self._score_co2(co2)
        
        # Light level score (if available)
        light_sensor = room_coord.entry.data.get("light_sensor")
        if light_sensor:
            light = await self._get_sensor_value(light_sensor)
            factors["light_level"] = self._score_light(light)
        
        # Calculate weighted overall score
        overall = 0.0
        total_weight = 0.0
        
        for factor, score in factors.items():
            weight = self.weights.get(factor, 0.0)
            overall += score * weight
            total_weight += weight
        
        if total_weight > 0:
            overall /= total_weight
        else:
            overall = 50.0  # Default if no factors
        
        return ComfortScore(
            score=overall,
            factors=factors,
            room=room_name
        )
    
    def _score_temperature(self, temp: float) -> float:
        """
        Score temperature comfort (0-100).
        
        Scoring:
        - 100: Within ideal range (68-72°F)
        - Decreases linearly outside range
        - 0: More than 10°F outside range
        """
        ideal_min, ideal_max = self.ideal_ranges["temperature"]
        
        if ideal_min <= temp <= ideal_max:
            return 100.0
        
        # Calculate distance from range
        if temp < ideal_min:
            distance = ideal_min - temp
        else:
            distance = temp - ideal_max
        
        # Linear decrease: 0 at 10°F distance
        score = max(0, 100 - (distance * 10))
        return score
    
    def _score_humidity(self, humidity: float) -> float:
        """Score humidity comfort (0-100)."""
        ideal_min, ideal_max = self.ideal_ranges["humidity"]
        
        if ideal_min <= humidity <= ideal_max:
            return 100.0
        
        if humidity < ideal_min:
            distance = ideal_min - humidity
        else:
            distance = humidity - ideal_max
        
        # Linear decrease: 0 at 30% distance
        score = max(0, 100 - (distance * 3.33))
        return score
    
    def _score_co2(self, co2: float) -> float:
        """Score CO2 air quality (0-100)."""
        if co2 <= 1000:
            return 100.0
        elif co2 <= 2000:
            # Linear decrease from 1000-2000 ppm
            return 100 - ((co2 - 1000) / 10)
        else:
            # Poor air quality
            return max(0, 20 - ((co2 - 2000) / 100))
    
    async def identify_bottleneck(self) -> Optional[ComfortBottleneck]:
        """
        Identify which room has the worst comfort and why.
        
        Returns:
            ComfortBottleneck with room, factor, and recommendation
        """
        # Calculate comfort for all rooms
        room_scores = []
        
        for room_coord in self._get_all_room_coordinators():
            room_name = room_coord.entry.data.get("room_name")
            score = await self.calculate_room_comfort(room_name)
            room_scores.append(score)
        
        if not room_scores:
            return None
        
        # Find lowest scoring room
        worst = min(room_scores, key=lambda s: s.score)
        
        # Find worst factor in that room
        if worst.factors:
            worst_factor = min(worst.factors.items(), key=lambda f: f[1])
            
            return ComfortBottleneck(
                room=worst.room,
                score=worst.score,
                factor=worst_factor[0],
                factor_score=worst_factor[1],
                recommendation=self._get_recommendation(
                    worst.room,
                    worst_factor[0],
                    worst_factor[1]
                )
            )
        
        return None
    
    def _get_recommendation(
        self,
        room: str,
        factor: str,
        score: float
    ) -> str:
        """Generate recommendation for improving comfort."""
        if factor == "temperature":
            if score < 50:
                return f"Adjust {room} thermostat or improve HVAC balancing"
        elif factor == "humidity":
            if score < 50:
                return f"Consider humidifier/dehumidifier for {room}"
        elif factor == "air_quality":
            if score < 50:
                return f"Increase ventilation or run air purifier in {room}"
        
        return f"Optimize {factor} in {room}"
```

---

### 4. HVAC Coordinator

**Purpose:** Coordinate HVAC zones to prevent conflicts and optimize efficiency.

#### Architecture

```python
# domain_coordinators/hvac.py

class HVACCoordinator:
    """
    Whole-house HVAC coordination.
    
    Problems Solved:
    1. Heat call conflicts (multiple zones calling simultaneously)
    2. Zone fighting (heating/cooling at same time)
    3. Inefficient cycling (short on/off cycles)
    4. Poor balancing (some zones always satisfied, others never)
    
    Solutions:
    1. Staggered heat calls (prioritize, don't call all at once)
    2. Conflict detection (prevent simultaneous heating/cooling)
    3. Minimum cycle times (prevent short cycling)
    4. Zone balancing (give struggling zones priority)
    """
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize HVAC coordinator."""
        self.hass = hass
        
        # Track zone states
        self.zones: Dict[str, ZoneHVACState] = {}
        
        # Track heat call history
        self.heat_call_history: List[HeatCallEvent] = []
        
        # Configuration
        self.max_simultaneous_zones = 3  # Don't run more than 3 zones at once
        self.min_cycle_time = 300        # 5 minutes minimum
        self.stagger_delay = 60          # 60 seconds between zone starts
    
    async def prioritize_heat_calls(self) -> List[str]:
        """
        Prioritize which zones should call for heat.
        
        Priority factors:
        1. Temperature delta (how far from setpoint)
        2. Occupancy (occupied zones prioritized)
        3. Time waiting (zones that haven't run recently)
        4. Historical struggle (zones that never reach setpoint)
        
        Returns:
            List of zone names in priority order
        """
        priorities = []
        
        for zone_name, zone_state in self.zones.items():
            # Calculate temperature delta
            temp_delta = abs(zone_state.setpoint - zone_state.current_temp)
            
            # Check occupancy
            is_occupied = await self._is_zone_occupied(zone_name)
            
            # Check time since last run
            time_since_run = self._get_time_since_last_run(zone_name)
            
            # Calculate priority score
            priority = 0.0
            
            # Temperature delta (0-10 points)
            priority += min(temp_delta * 2, 10)
            
            # Occupancy bonus (0-5 points)
            if is_occupied:
                priority += 5
            
            # Time waiting bonus (0-5 points)
            if time_since_run > 1800:  # 30 minutes
                priority += 5
            elif time_since_run > 3600:  # 1 hour
                priority += 10
            
            priorities.append((zone_name, priority))
        
        # Sort by priority (highest first)
        priorities.sort(key=lambda x: x[1], reverse=True)
        
        return [zone for zone, _ in priorities]
    
    async def execute_staggered_heat_calls(self, prioritized_zones: List[str]) -> None:
        """
        Execute heat calls with staggering to prevent overload.
        
        Logic:
        1. Start highest priority zone first
        2. Wait stagger_delay seconds
        3. Start next zone if max_simultaneous not reached
        4. Repeat
        """
        active_zones = self._get_active_zones()
        
        for zone in prioritized_zones:
            # Check if we're at max simultaneous
            if len(active_zones) >= self.max_simultaneous_zones:
                _LOGGER.debug(
                    f"HVAC: Max simultaneous zones reached ({self.max_simultaneous_zones}), "
                    f"deferring {zone}"
                )
                break
            
            # Check if zone needs heat
            zone_state = self.zones.get(zone)
            if not zone_state or not zone_state.needs_heat:
                continue
            
            # Start heat call
            await self._start_zone_heat_call(zone)
            active_zones.append(zone)
            
            # Stagger next call
            if zone != prioritized_zones[-1]:  # Not last zone
                await asyncio.sleep(self.stagger_delay)
    
    async def detect_conflicts(self) -> List[HVACConflict]:
        """
        Detect HVAC conflicts.
        
        Conflicts:
        1. Simultaneous heating/cooling in same zone
        2. Too many zones calling simultaneously
        3. Zone calling before minimum cycle time
        4. Outside air damper open when cooling
        """
        conflicts = []
        
        for zone_name, zone_state in self.zones.items():
            # Check heating/cooling conflict
            if zone_state.heating and zone_state.cooling:
                conflicts.append(HVACConflict(
                    type="simultaneous_heat_cool",
                    zone=zone_name,
                    severity="high",
                    message=f"{zone_name} heating and cooling simultaneously"
                ))
            
            # Check cycle time
            time_since_last = self._get_time_since_last_run(zone_name)
            if zone_state.calling and time_since_last < self.min_cycle_time:
                conflicts.append(HVACConflict(
                    type="short_cycle",
                    zone=zone_name,
                    severity="medium",
                    message=f"{zone_name} calling before minimum cycle time"
                ))
        
        # Check total simultaneous
        active = len(self._get_active_zones())
        if active > self.max_simultaneous_zones:
            conflicts.append(HVACConflict(
                type="too_many_zones",
                severity="high",
                message=f"{active} zones active (max: {self.max_simultaneous_zones})"
            ))
        
        return conflicts
```

---

## 🔗 INTER-COORDINATOR COMMUNICATION

### Event Bus Architecture

```python
# domain_coordinators/event_bus.py

class DomainEventBus:
    """
    Central event bus for inter-coordinator communication.
    
    Coordinators publish events:
    - Security: "security_mode_changed", "anomaly_detected"
    - Energy: "battery_low", "load_shedding_active"
    - Comfort: "comfort_degraded", "bottleneck_identified"
    - HVAC: "conflict_detected", "zone_priority_changed"
    
    Coordinators subscribe to events from other coordinators
    to coordinate responses.
    """
    
    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize event bus."""
        self.hass = hass
        self._subscribers: Dict[str, List[Callable]] = {}
    
    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Subscribe to domain events."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        
        self._subscribers[event_type].append(callback)
    
    async def publish(self, event: DomainEvent) -> None:
        """Publish domain event to subscribers."""
        event_type = event.type
        
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    await callback(event)
                except Exception as e:
                    _LOGGER.error(f"Event bus callback failed: {e}")


# Example: Security mode changes affect HVAC priorities
class HVACCoordinator:
    def __init__(self, ...):
        # Subscribe to security events
        event_bus.subscribe("security_mode_changed", self._on_security_mode_changed)
    
    async def _on_security_mode_changed(self, event: DomainEvent) -> None:
        """Adjust HVAC when security mode changes."""
        new_mode = event.data.get("mode")
        
        if new_mode == "away":
            # Reduce all setpoints by 3°F to save energy
            for zone in self.zones:
                await self._reduce_setpoint(zone, delta=-3.0)
        
        elif new_mode == "home":
            # Restore normal setpoints
            for zone in self.zones:
                await self._restore_setpoint(zone)
```

### Priority Resolution

```python
# domain_coordinators/priority.py

class CoordinatorPriority(Enum):
    """Priority levels for coordinator conflicts."""
    CRITICAL = 1    # Security (always wins)
    HIGH = 2        # Energy (battery protection)
    MEDIUM = 3      # Comfort (user experience)
    LOW = 4         # HVAC (efficiency optimization)


def resolve_conflict(
    security_req: Optional[Action],
    energy_req: Optional[Action],
    comfort_req: Optional[Action],
    hvac_req: Optional[Action]
) -> Action:
    """
    Resolve conflicts between coordinator requests.
    
    Priority order:
    1. Security (always wins)
    2. Energy (if battery critically low)
    3. Comfort (if significant degradation)
    4. HVAC (optimization)
    """
    if security_req and security_req.priority == CoordinatorPriority.CRITICAL:
        return security_req
    
    if energy_req and energy_req.priority == CoordinatorPriority.HIGH:
        return energy_req
    
    if comfort_req and comfort_req.priority == CoordinatorPriority.MEDIUM:
        return comfort_req
    
    if hvac_req:
        return hvac_req
    
    return None  # No action needed
```

---

## 📊 IMPLEMENTATION PLAN

### Phase 1: Foundation (3-4 hours)
- [ ] Create `domain_coordinators/` directory structure
- [ ] Implement base DomainCoordinator class
- [ ] Create event bus architecture
- [ ] Add coordinator discovery to __init__.py
- [ ] Create coordinator device in HA

### Phase 2: Security Coordinator (3-4 hours)
- [ ] Implement SecurityCoordinator
- [ ] Add perimeter monitoring
- [ ] Add anomaly detection logic
- [ ] Create security sensors
- [ ] Test security mode transitions

### Phase 3: Energy Coordinator (4-5 hours)
- [ ] Implement EnergyCoordinator
- [ ] Integrate with Enphase batteries
- [ ] Add TOU rate logic
- [ ] Implement load shedding
- [ ] Create energy sensors
- [ ] Test battery optimization

### Phase 4: Comfort Coordinator (2-3 hours)
- [ ] Implement ComfortCoordinator
- [ ] Add multi-factor comfort scoring
- [ ] Add bottleneck identification
- [ ] Create comfort sensors
- [ ] Test comfort calculations

### Phase 5: HVAC Coordinator (3-4 hours)
- [ ] Implement HVACCoordinator
- [ ] Add zone prioritization
- [ ] Add conflict detection
- [ ] Implement staggered heat calls
- [ ] Create HVAC sensors
- [ ] Test zone coordination

**Total: 15-20 hours**

---

## 🧪 TESTING STRATEGY

### Unit Tests
- Individual coordinator logic
- Comfort scoring algorithms
- Priority resolution
- Event bus message passing

### Integration Tests
- Cross-coordinator communication
- Conflict resolution
- End-to-end scenarios

### Hardware Tests
- Battery optimization with real Enphase system
- HVAC coordination with real zones
- Security monitoring with real sensors

---

## 🎯 SUCCESS CRITERIA

**Security:**
- ✅ Detects perimeter breaches within 5 seconds
- ✅ Sends critical alerts reliably
- ✅ Transitions security modes automatically

**Energy:**
- ✅ Reduces on-peak grid import by 30%
- ✅ Optimizes battery cycles for longevity
- ✅ Executes load shedding when needed

**Comfort:**
- ✅ Identifies comfort bottlenecks accurately
- ✅ Multi-factor scores reflect actual comfort
- ✅ Recommendations improve comfort metrics

**HVAC:**
- ✅ Eliminates heat call conflicts
- ✅ Reduces simultaneous zone calls by 50%
- ✅ Improves zone balance (all zones satisfied)

---

**PLANNING v3.6.0 - Domain Coordinators**  
**Status:** Complete specification  
**Ready for:** Session 3 (Opus 4.5)  
**Estimated Effort:** 15-20 hours  
**Dependencies:** v3.4.0 deployed  
**Target:** Q3 2026

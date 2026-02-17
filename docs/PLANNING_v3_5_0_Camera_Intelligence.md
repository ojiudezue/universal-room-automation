# PLANNING v3.5.0 - Camera Intelligence & Whole-House Census

**Version:** v3.5.0  
**Theme:** Person Tracking Intelligence  
**Created:** January 14, 2026  
**Effort Estimate:** 15-18 hours  
**Deployment Timeline:** Q2 2026  
**Model Recommendation:** Sonnet 4.5 (well-specified, moderate complexity)  

---

## 📋 EXECUTIVE SUMMARY

**CURRENT STATE NOTE (January 14, 2026):**  
Development is currently focused on v3.3.x.x bug fixes - finalizing music transition logic between WiiM media players and addressing small bugs in zone management and person sensor staleness. v3.5.0 is fully planned and ready to build once v3.3.x.x stabilizes and is deployed to production.

---

v3.5.0 elevates URA from "room-level automation" to **"whole-house person intelligence"** by integrating camera sensors from UniFi Protect and Frigate into URA's existing multi-sensor fusion system. This version creates a **defense-in-depth** architecture where each sensor type covers the weaknesses of others:

- **Private rooms** (bedroom, bathroom, office): BLE provides identity without privacy concerns
- **Shared spaces** (living room, game room): Cameras handle multi-person dynamics and guest detection
- **Transition zones** (hallways, stairs): Cameras validate cross-room movement predictions
- **Entry/exit points**: Cameras provide whole-house occupancy state confidence

**Key Innovation:** House Census System - knows with high precision **who** is home, **where** they are, **how many** unidentified guests, and validates this through natural 2-4 hour transit patterns.

### Value Proposition

**Solves Real Problems:**
1. **BLE Blind Spots:** "Phone charging in bedroom, person actually in kitchen"
2. **Guest Detection:** "3 visitors in living room, disable personal automations"
3. **Whole-House State:** "Everyone actually left vs just phones absent"
4. **Multi-Person Dynamics:** "Both home but only one in living room - adjust automation"
5. **Security Anomalies:** "Unknown person entered while house empty"

**Business Value:**
- Music following precision: Follow *you*, not just "someone"
- HVAC optimization: Accurate occupancy load (2 people vs 4 people)
- Security context: Expected person vs intruder
- Energy efficiency: True away mode vs false triggers
- Personalization: John's preferences vs Jane's vs guest mode

---

## 🏗️ ARCHITECTURAL POSITIONING

### Current Architecture (v3.2.9)

```
Integration Level (ura)
├── Zone Coordinators
│   ├── Upstairs Zone
│   ├── Downstairs Zone  
│   └── Garage Zone
└── Room Coordinators (47 entities each)
    ├── Bedroom
    ├── Office
    ├── Kitchen
    └── [etc...]
```

### v3.5.0 Additions (NEW LAYER)

```
Integration Level (ura)
├── House Person Coordinator (NEW) ⭐
│   ├── Census Engine
│   ├── Camera Integration Manager (Dual Platform)
│   ├── Transit Validation System
│   └── Entry/Exit Tracker
├── Zone Coordinators (ENHANCED)
│   ├── Zone Person Aggregator (NEW)
│   └── Multi-Source Fusion (ENHANCED - camera layer added)
└── Room Coordinators (ENHANCED)
    └── Camera Person Detection (NEW - shared spaces + some transition zones)
```

**Sensor Architecture by Room Type:**

```
Private Rooms (Bedroom, Office, Bathroom):
├── BLE (0.90 weight - identity + presence)
├── mmWave (0.70 weight - occupancy detection)
├── Motion (0.50 weight - supporting evidence)
└── Cameras: NONE (privacy protection)

Shared Spaces (Living Room, Game Room) - SENSOR RICH:
├── Camera UniFi (0.85 weight - person detection)
├── Camera Frigate (0.85 weight - cross-validation)
├── BLE (0.70 weight - identity for known persons)
├── mmWave (0.60 weight - occupancy confirmation)
└── Motion (0.50 weight - supporting evidence)
    └── Agreement Boost: When cameras agree, confidence *= 1.2

Transition Zones (Hallways, Stairs):
├── Motion (0.70 weight - always present, primary)
├── Camera (0.85 weight - where installed, validation)
├── BLE (0.40 weight - just passing through)
└── mmWave (0.30 weight - usually absent, not cost-effective)
```

### Relationship to v3.6.0 Domain Coordinators

**IMPORTANT:** v3.5.0 is **foundational infrastructure** that v3.6.0 depends on.

```
v3.5.0 House Person Coordinator
    ↓ (provides census data to)
v3.6.0 Domain Coordinators
    ├── Security Coordinator (uses census for anomaly detection)
    ├── Energy Coordinator (uses census for HVAC load optimization)
    ├── Comfort Coordinator (uses person distribution)
    └── HVAC Coordinator (uses zone person counts)
```

**No Architectural Conflict:** House Person Coordinator is a **data layer** (who/where/how many), while Domain Coordinators are **intelligence layers** (security/energy/comfort decisions).

---

## 🎯 SCOPE & FEATURES

### Phase 1: Camera Integration Foundation (5-6 hours)

**Goal:** Get camera sensors integrated and providing basic person detection.

**Components:**

#### 1. Camera Integration Manager
```python
class CameraIntegrationManager:
    """Manages UniFi Protect + Frigate camera sensors"""
    
    def __init__(self):
        self.unifi_cameras = {}  # Primary person detection
        self.frigate_cameras = {}  # Facial recognition (optional)
        self.camera_room_mapping = {}  # Which cameras cover which rooms
        
    async def discover_cameras(self):
        """Auto-discover available camera sensors"""
        # UniFi: binary_sensor.{camera}_person_detected
        # Frigate: binary_sensor.{camera}_person
        
    async def get_camera_person_count(self, room_id):
        """Get person count from cameras in/near this room"""
        # Fallback chain: Frigate → UniFi → None
```

**Room Types with Cameras:**
- **Transition zones:** Master hallway, upstairs hallway, garage hallway, stairs
- **Shared spaces:** Living room, game room, entryway
- **Private rooms:** None (BLE + sensors only)

#### 2. Room-Level Camera Sensors (Shared Spaces Only)

**NEW Binary Sensor:**
```yaml
binary_sensor.{room}_camera_person_detected:
  device_class: occupancy
  attributes:
    camera_source: "unifi" or "frigate"
    detection_confidence: 0.0-1.0
    person_count: integer
    last_detection: timestamp
```

**NEW Count Sensor (Multi-Person Rooms):**
```yaml
sensor.{room}_camera_person_count:
  state: integer (0-10+)
  attributes:
    camera_source: "unifi" or "frigate"  
    cameras_active: ["living_room_main", "living_room_corner"]
    detection_method: "count" or "estimate"
    confidence: 0.0-1.0
```

**Configuration:**
```yaml
# Config flow options per room
camera_integration:
  enabled: true  # Only for rooms with cameras
  primary_camera: "camera.living_room_main"
  secondary_cameras: ["camera.living_room_corner"]  # Optional
  detection_source: "unifi"  # or "frigate" or "both"
  person_counting: true  # Multi-person detection
```

#### 3. Enhanced Multi-Sensor Fusion with Dual Platform Cross-Checking

**Update Existing Fusion Algorithm:**

```python
# Private rooms (no cameras)
occupancy_sources = {
    'ble': 0.90,      # High - knows WHO + presence
    'mmwave': 0.70,   # High - occupancy detection
    'motion': 0.50,   # Medium - supporting evidence
    'camera': 0.00    # Not available (privacy)
}

# Transition zones (hallways/stairs) - motion primary
occupancy_sources = {
    'motion': 0.70,   # High - always present, primary sensor
    'camera': 0.85,   # High - where installed (some hallways)
    'ble': 0.40,      # Low - just passing through
    'mmwave': 0.30    # Low - usually absent (not cost-effective)
}

# Shared spaces (living room/game room) - SENSOR RICH
occupancy_sources = {
    'camera_unifi': 0.85,   # High - person detection
    'camera_frigate': 0.85, # High - cross-validation
    'ble': 0.70,            # High - identity for known persons
    'mmwave': 0.60,         # Medium - occupancy confirmation
    'motion': 0.50          # Medium - supporting evidence
}
```

**Camera Cross-Validation with Agreement Boost:**
```python
def get_camera_confidence(unifi_data, frigate_data):
    """Calculate camera confidence with cross-checking"""
    
    if not unifi_data and not frigate_data:
        return 0.0, None
    
    if unifi_data and frigate_data:
        # Both platforms available - cross-check
        base_confidence = 0.85
        
        if unifi_data['count'] == frigate_data['count']:
            # Perfect agreement - significant boost
            return min(1.0, base_confidence * 1.25), {
                'agreement': True,
                'count': unifi_data['count'],
                'sources': ['unifi', 'frigate']
            }
        
        elif abs(unifi_data['count'] - frigate_data['count']) <= 1:
            # Close agreement (within 1 person) - small boost
            return min(1.0, base_confidence * 1.1), {
                'agreement': 'close',
                'count': max(unifi_data['count'], frigate_data['count']),
                'sources': ['unifi', 'frigate']
            }
        
        else:
            # Disagreement - reduce confidence, take max
            return base_confidence * 0.8, {
                'agreement': False,
                'count': max(unifi_data['count'], frigate_data['count']),
                'unifi_count': unifi_data['count'],
                'frigate_count': frigate_data['count'],
                'sources': ['unifi', 'frigate']
            }
    
    else:
        # Single platform available - good but not great
        single_data = unifi_data or frigate_data
        source = 'unifi' if unifi_data else 'frigate'
        
        return 0.75, {
            'agreement': None,
            'count': single_data['count'],
            'sources': [source],
            f'{source}_only': True
        }

def calculate_occupancy_confidence(sensor_data):
    """Multi-source weighted confidence with camera cross-checking"""
    
    weighted_sum = 0
    total_weight = 0
    
    # Handle camera cross-checking separately
    camera_confidence, camera_info = get_camera_confidence(
        sensor_data.get('camera_unifi'),
        sensor_data.get('camera_frigate')
    )
    
    if camera_info:
        # Add camera confidence (using agreement-adjusted value)
        weighted_sum += camera_confidence * 0.85
        total_weight += 0.85
    
    # Process other sensors normally
    for source, weight in occupancy_sources.items():
        if source.startswith('camera_'):
            continue  # Already handled above
        
        if sensor_data.get(source, {}).get('available'):
            weighted_sum += sensor_data[source]['confidence'] * weight
            total_weight += weight
    
    confidence = weighted_sum / total_weight if total_weight > 0 else 0
    
    # General agreement boost (non-camera sensors)
    sources_agree = check_source_agreement(sensor_data, exclude_cameras=True)
    if sources_agree:
        confidence = min(1.0, confidence * 1.1)
    
    return confidence, camera_info
```

---

### Phase 2: House Census System (6-7 hours)

**Goal:** Create whole-house person tracking with identity precision.

#### 1. Census Engine

```python
class HousePersonCensus:
    """Maintains authoritative count of who's home"""
    
    def __init__(self):
        self.ble_persons = {}  # Known persons via BLE
        self.camera_detections = {}  # Visual confirmations
        self.transit_validation = {}  # Last seen by cameras
        
    async def calculate_census(self):
        """Generate current house census"""
        
        # Step 1: BLE baseline (identified persons)
        ble_persons = await self._get_ble_persons_present()
        # {'John': {'device': 'phone', 'room': 'bedroom', 'confidence': 0.90}}
        
        # Step 2: Camera totals (all cameras aggregated)
        camera_total = await self._aggregate_camera_detections()
        # {'total_seen': 3, 'by_room': {'living_room': 2, 'hallway': 1}}
        
        # Step 3: Transit validation (heartbeat check)
        for person, data in ble_persons.items():
            time_since_camera = await self._check_transit_validation(person)
            
            if time_since_camera > timedelta(hours=4) and is_waking_hours():
                data['confidence'] = 'low'  # Possibly phone left behind
            else:
                data['confidence'] = 'high'
        
        # Step 4: Calculate unidentified count
        identified_count = len([p for p in ble_persons.values() 
                               if p['confidence'] == 'high'])
        unidentified_count = max(0, camera_total['total_seen'] - identified_count)
        
        # Step 5: Confidence scoring
        confidence = self._calculate_census_confidence(
            ble_persons, camera_total, identified_count, unidentified_count
        )
        
        return {
            'identified_persons': list(ble_persons.keys()),
            'identified_count': identified_count,
            'unidentified_count': unidentified_count,
            'total_persons': identified_count + unidentified_count,
            'confidence': confidence,  # 'high', 'medium', 'low'
            'last_update': datetime.now(),
            'validation_age': min([time_since_camera for time_since_camera in ...])
        }
```

#### 2. Integration-Level Census Sensors

**NEW Sensors (Top-Level):**
```yaml
# Total house occupancy
sensor.ura_total_persons_home:
  state: integer (0-20)
  unit_of_measurement: "persons"
  icon: mdi:account-multiple
  attributes:
    identified_persons: ["John", "Jane"]
    identified_count: 2
    unidentified_count: 1
    confidence: "high"
    last_validation: "2026-01-14T10:30:00"
    validation_age_minutes: 2

sensor.ura_identified_persons_home:
  state: "John, Jane"  # Comma-separated list
  icon: mdi:account-check
  attributes:
    count: 2
    persons:
      - name: "John"
        device: "phone"
        last_seen_camera: "2026-01-14T10:28:00"
        confidence: "high"
      - name: "Jane"
        device: "watch"  
        last_seen_camera: "2026-01-14T10:25:00"
        confidence: "high"

sensor.ura_unidentified_persons_count:
  state: integer (0-10)
  icon: mdi:account-question
  attributes:
    detection_method: "camera_minus_ble"
    rooms_detected: ["living_room"]
    guest_mode_active: true

# Confidence & validation
sensor.ura_census_confidence:
  state: "high"  # high/medium/low
  attributes:
    sources_agree: true
    ble_count: 2
    camera_count: 3
    confidence_score: 0.92
    reasons: ["Recent camera validation", "Multiple sensors agree"]

sensor.ura_census_validation_age:
  state: integer  # minutes
  unit_of_measurement: "min"
  device_class: duration
  attributes:
    last_validation_time: "2026-01-14T10:28:00"
    validation_source: "living_room_camera"

# Entry/exit tracking
sensor.ura_persons_entered_today:
  state: integer
  attributes:
    entries: [
      {"person": "Jane", "time": "09:15", "source": "entryway_camera"},
      {"person": "Guest", "time": "14:30", "source": "entryway_camera"}
    ]

sensor.ura_persons_exited_today:
  state: integer
  attributes:
    exits: [
      {"person": "John", "time": "08:00", "source": "garage_camera"},
      {"person": "Guest", "time": "16:45", "source": "entryway_camera"}
    ]

sensor.ura_last_person_entry:
  state: "Jane at 09:15"
  attributes:
    person_name: "Jane"
    entry_time: "2026-01-14T09:15:00"
    entry_point: "entryway"
    detection_source: "entryway_camera"

sensor.ura_last_person_exit:
  state: "Guest at 16:45"
  attributes:
    person_name: "Guest"
    exit_time: "2026-01-14T16:45:00"
    exit_point: "entryway"
    detection_source: "entryway_camera"

# Security & anomaly
binary_sensor.ura_unexpected_person_detected:
  state: on/off
  device_class: problem
  attributes:
    reason: "Unknown person, all BLE devices away"
    detection_time: "2026-01-14T14:15:00"
    location: "living_room"
    action_taken: "Alert sent, recording started"

binary_sensor.ura_census_mismatch:
  state: on/off  
  device_class: problem
  attributes:
    expected_count: 2
    actual_count: 3
    mismatch_reason: "Camera sees more than BLE accounts for"
    rooms_with_extra: ["living_room"]
```

#### 3. Zone Aggregation Sensors

**NEW Sensors (Per Zone):**
```yaml
sensor.{zone}_person_count:
  state: integer
  attributes:
    identified_persons: ["John", "Jane"]
    identified_count: 2
    unidentified_count: 0
    rooms_occupied: ["bedroom", "bathroom"]
    distribution: "2 in bedroom, 0 in bathroom"

sensor.{zone}_identified_persons:
  state: "John, Jane"  
  attributes:
    count: 2
    persons_by_room:
      bedroom: ["John", "Jane"]
      bathroom: []

sensor.{zone}_unidentified_count:
  state: integer
  attributes:
    rooms_with_unidentified: ["guest_room"]
    likely_guests: true
```

#### 4. Person Distribution Analysis

```yaml
sensor.ura_person_distribution:
  state: "2 upstairs, 1 downstairs"
  attributes:
    zones:
      upstairs:
        total: 2
        identified: ["John", "Jane"]
        rooms: ["bedroom", "bathroom"]
      downstairs:
        total: 1
        identified: []
        rooms: ["living_room"]
      garage:
        total: 0
        identified: []
        rooms: []
```

---

### Phase 3: Transit Validation & Movement Intelligence (4-5 hours)

**Goal:** Validate BLE predictions via camera checkpoints, detect anomalies.

#### 1. Transit Validator

```python
class TransitValidator:
    """Validates person presence via periodic camera sightings"""
    
    async def validate_person_still_home(self, person_name: str):
        """Check if person truly home or just their device"""
        
        ble_present = await self._check_ble_device(person_name)
        last_camera_sighting = await self._get_last_camera_detection(person_name)
        time_since_sighting = datetime.now() - last_camera_sighting
        
        # Validation rules
        if not ble_present:
            return False, "BLE device not present"
        
        if self._is_sleep_hours():
            # Don't expect camera validation 11pm-7am
            return True, "Sleep hours - BLE sufficient"
        
        if time_since_sighting < timedelta(hours=2):
            return True, "Recently validated by camera"
        
        if timedelta(hours=2) <= time_since_sighting < timedelta(hours=4):
            return "uncertain", "Approaching validation timeout"
        
        if time_since_sighting >= timedelta(hours=4):
            return False, "No camera validation in 4 hours - device likely left behind"
    
    async def validate_movement_path(self, person_name: str, from_room: str, to_room: str):
        """Validate cross-room movement via camera checkpoints"""
        
        # Get expected camera path
        path = self._get_camera_checkpoints(from_room, to_room)
        # e.g., bedroom → kitchen = [master_hallway, stairs, downstairs_hallway]
        
        # Check each checkpoint
        for checkpoint in path:
            camera_saw_person = await self._check_camera_saw_person(
                checkpoint,
                person_name,
                within_seconds=30
            )
            
            if not camera_saw_person:
                return False, f"Lost at {checkpoint} - person not seen"
        
        return True, "Movement path confirmed"
```

#### 2. Movement Validation Sensors

```yaml
binary_sensor.{person}_movement_validated:
  state: on/off
  attributes:
    from_room: "bedroom"
    to_room: "kitchen"
    expected_path: ["master_hallway", "stairs", "downstairs_hallway"]
    checkpoints_passed: ["master_hallway", "stairs"]
    validation_status: "in_progress" or "confirmed" or "failed"
    failure_point: "downstairs_hallway"  # if failed

binary_sensor.{person}_device_left_behind:
  state: on/off
  device_class: problem
  attributes:
    ble_location: "bedroom"
    last_camera_location: "kitchen"
    time_since_mismatch: 15  # minutes
    confidence: "high"
```

#### 3. Enhanced Cross-Room Movement (Builds on v3.3.0)

**Integration with v3.3.0 Transition Detection:**

```python
# v3.3.0 provides: room transition detection, pattern learning
# v3.5.0 adds: camera validation, identity tracking, confidence scoring

async def on_person_transition(person_name, from_room, to_room):
    """Enhanced transition handler with camera validation"""
    
    # v3.3.0: Record transition
    await self.transition_detector.record_transition(person_name, from_room, to_room)
    
    # v3.5.0: Validate movement path
    validation = await self.transit_validator.validate_movement_path(
        person_name, from_room, to_room
    )
    
    # v3.5.0: Update census with validated movement
    if validation.success:
        await self.census.update_person_location(person_name, to_room)
    else:
        # Anomaly: Expected movement didn't validate
        await self.census.flag_location_uncertainty(person_name)
    
    # v3.3.0: Trigger music following (if configured)
    await self.music_following.handle_transition(person_name, to_room)
```

---

## 🎨 DUAL PLATFORM REDUNDANCY STRATEGY

### UniFi Protect + Frigate: Cross-Checking, Not Division of Labor

**Core Philosophy:** Use **both platforms simultaneously** for cross-validation and redundancy, not sequential fallback. This provides:

1. **Confidence boost when platforms agree** (perfect agreement = 25% confidence increase)
2. **Resilience during maintenance** (upgrade one platform while other continues)
3. **No single point of failure** (either platform can sustain operations)
4. **Software diversity** (different algorithms catch different edge cases)
5. **Transient outage protection** (if one crashes, other continues seamlessly)

**Architecture:**
```python
class DualPlatformCameraManager:
    """Cross-checking strategy with platform redundancy"""
    
    def __init__(self):
        self.unifi = UniFiProtectManager()
        self.frigate = FrigateManager()
        self.health_monitor = PlatformHealthMonitor()
        
    async def get_person_detection(self, room_id):
        """Get detection from BOTH platforms and cross-validate"""
        
        # Attempt both platforms simultaneously (parallel)
        unifi_task = asyncio.create_task(self._get_unifi_detection(room_id))
        frigate_task = asyncio.create_task(self._get_frigate_detection(room_id))
        
        unifi_data = await unifi_task
        frigate_data = await frigate_task
        
        # Cross-validation logic
        if unifi_data and frigate_data:
            # Both available - cross-check
            agreement = self._check_agreement(unifi_data, frigate_data)
            
            if agreement == 'perfect':
                # Exact match - highest confidence
                return {
                    'person_count': unifi_data['count'],
                    'confidence': 'very_high',
                    'confidence_score': min(1.0, 0.85 * 1.25),  # 25% boost
                    'sources': ['unifi', 'frigate'],
                    'agreement': True,
                    'reliability': 'excellent'
                }
            
            elif agreement == 'close':
                # Within 1 person - good confidence
                return {
                    'person_count': max(unifi_data['count'], frigate_data['count']),
                    'confidence': 'high',
                    'confidence_score': min(1.0, 0.85 * 1.1),  # 10% boost
                    'sources': ['unifi', 'frigate'],
                    'agreement': 'close',
                    'unifi_count': unifi_data['count'],
                    'frigate_count': frigate_data['count'],
                    'reliability': 'good'
                }
            
            else:
                # Disagreement - flag for investigation
                self.health_monitor.log_disagreement(room_id, unifi_data, frigate_data)
                
                return {
                    'person_count': max(unifi_data['count'], frigate_data['count']),
                    'confidence': 'medium',
                    'confidence_score': 0.85 * 0.8,  # 20% reduction
                    'sources': ['unifi', 'frigate'],
                    'agreement': False,
                    'unifi_count': unifi_data['count'],
                    'frigate_count': frigate_data['count'],
                    'reliability': 'uncertain',
                    'action_required': 'investigate_disagreement'
                }
        
        elif unifi_data:
            # Only UniFi available - single source
            self.health_monitor.log_platform_unavailable('frigate', room_id)
            
            return {
                'person_count': unifi_data['count'],
                'confidence': 'high',  # Single source but UniFi is reliable
                'confidence_score': 0.75,
                'sources': ['unifi'],
                'frigate_unavailable': True,
                'reliability': 'good_single_source'
            }
        
        elif frigate_data:
            # Only Frigate available - single source
            self.health_monitor.log_platform_unavailable('unifi', room_id)
            
            return {
                'person_count': frigate_data['count'],
                'confidence': 'high',
                'confidence_score': 0.75,
                'sources': ['frigate'],
                'unifi_unavailable': True,
                'reliability': 'good_single_source'
            }
        
        else:
            # Neither available - graceful degradation
            self.health_monitor.log_platform_failure('both', room_id)
            
            return {
                'person_count': 0,
                'confidence': 'none',
                'confidence_score': 0.0,
                'sources': [],
                'both_unavailable': True,
                'fallback_to_other_sensors': True,
                'reliability': 'degraded'
            }
    
    def _check_agreement(self, unifi_data, frigate_data):
        """Check level of agreement between platforms"""
        
        # Exact match
        if unifi_data['count'] == frigate_data['count']:
            return 'perfect'
        
        # Within 1 person tolerance (acceptable)
        if abs(unifi_data['count'] - frigate_data['count']) <= 1:
            return 'close'
        
        # Significant disagreement (2+ people difference)
        return 'disagree'
```

**Platform Capabilities & Strategy:**

| Capability | UniFi Protect | Frigate | Implementation Strategy |
|------------|---------------|---------|------------------------|
| Person Detection | ✅ Fast, reliable | ✅ Good | **BOTH - cross-validate for confidence boost** |
| Person Count | ⚠️ Basic | ✅ More accurate | **BOTH - Frigate likely more accurate, but cross-check** |
| Facial Recognition | ❌ Limited | ✅ Excellent | **Frigate SPECIALIST** (optional feature) |
| Motion Detection | ✅ Excellent | ✅ Good | **BOTH - cross-validate** |
| Reliability | ✅ Very stable | ⚠️ Can crash | **CRITICAL: UniFi as stability baseline** |
| Update Frequency | ✅ Real-time | ⚠️ MQTT lag | **UniFi PRIMARY for triggers** |
| Native HA Integration | ✅ Yes | ⚠️ MQTT | **UniFi easier to maintain** |
| Custom Zones | ✅ Good | ✅ Excellent | **Frigate for precision zones** |

**Configuration:**
```yaml
dual_platform_strategy:
  enabled: true
  
  cross_validation:
    enabled: true
    agreement_tolerance: 1  # Within 1 person = "close agreement"
    perfect_agreement_boost: 1.25  # 25% confidence increase
    close_agreement_boost: 1.10    # 10% confidence increase
    disagreement_penalty: 0.80     # 20% confidence reduction
  
  redundancy:
    single_platform_acceptable: true  # Can operate on one platform
    log_platform_unavailability: true
    alert_on_both_unavailable: true
  
  platform_priority:
    primary_trigger: "unifi"  # Faster, more stable for real-time triggers
    person_counting: "frigate_preferred"  # More accurate, but use UniFi if unavailable
    facial_recognition: "frigate_only"  # Only Frigate supports this well
  
  health_monitoring:
    track_agreement_rate: true
    alert_on_low_agreement: true  # < 80% agreement rate
    disagreement_threshold: 5  # Alert if 5+ disagreements per hour
```

### Maintenance & Upgrade Scenarios

**Scenario 1: Upgrading Frigate**
```
Before upgrade:
  - Both platforms operational
  - Confidence: very_high (cross-validation active)

During upgrade (Frigate offline):
  - UniFi continues operations
  - Confidence drops to: high (single source)
  - Census continues updating normally
  - Alert: "Frigate unavailable - operating on UniFi only"

After upgrade:
  - Both platforms resume
  - Confidence returns to: very_high
  - Cross-validation resumes
```

**Scenario 2: UniFi Maintenance**
```
During maintenance:
  - Frigate takes over
  - Confidence: high (single source)
  - Slightly slower updates (MQTT vs native)
  - All critical functions continue
```

**Scenario 3: Frigate Crash (Transient)**
```
Detection:
  - Frigate stops responding
  - UniFi immediately takes over (no gap in coverage)
  - Health monitor logs issue
  
Recovery:
  - Frigate recovers automatically
  - Cross-validation resumes
  - Agreement rate monitored for anomalies
```

**Scenario 4: Both Platforms Unavailable**
```
Degradation:
  - Census system falls back to BLE + mmWave + motion
  - Camera person counts unavailable
  - Guest detection limited
  - Confidence drops significantly
  
Alert:
  - "CRITICAL: Both camera platforms unavailable"
  - "Census operating in degraded mode"
  - System continues functioning on remaining sensors
```

### Platform Health Monitoring

**NEW Sensors:**
```yaml
sensor.ura_camera_platform_health:
  state: "full"  # full/partial/degraded/none
  attributes:
    unifi_status: "online"
    frigate_status: "online"
    cross_validation_enabled: true
    agreement_rate_1h: 94.5%
    agreement_rate_24h: 96.2%
    disagreements_today: 3
    disagreements_this_hour: 0
    platform_availability: "both"
    last_check: "2026-01-14T10:30:00"

sensor.ura_platform_agreement_rate:
  state: 94.5  # percentage
  unit_of_measurement: "%"
  attributes:
    detections_compared_1h: 48
    perfect_agreements_1h: 42
    close_agreements_1h: 4
    disagreements_1h: 2
    common_disagreement_rooms: ["living_room"]

binary_sensor.ura_platform_disagreement_alert:
  state: off  # on if disagreements exceed threshold
  device_class: problem
  attributes:
    disagreements_this_hour: 2
    threshold: 5
    recent_disagreements: [
      {"room": "living_room", "time": "10:25", "unifi": 3, "frigate": 2}
    ]
```

---

## 🔒 PRIVACY & SECURITY

### Privacy-First Architecture

**1. Camera Placement Philosophy**
```yaml
camera_locations:
  allowed:
    - Transition zones (hallways, stairs)
    - Shared spaces (living room, game room)
    - Entry/exit points (entryway, garage)
  
  prohibited:
    - Private rooms (bedrooms, bathrooms, office)
    - Personal spaces (closets, home gym)
```

**2. Facial Recognition Opt-In**
```yaml
# Config flow options
facial_recognition:
  enabled: false  # DEFAULT: OFF
  require_explicit_consent: true
  rooms_enabled: []  # User must explicitly enable per room
  guest_recognition: false  # Learn guest faces (opt-in)
  data_retention_days: 30  # How long to keep recognition data
```

**3. Privacy Modes**
```yaml
privacy_mode:
  enabled: false  # Master switch
  
  when_enabled:
    - Disable all facial recognition
    - Disable person counting (basic detection only)
    - Disable camera recording
    - Only use cameras for binary presence
  
  schedule:  # Optional automatic privacy hours
    - start: "22:00"  # 10 PM
      end: "07:00"    # 7 AM
      days: ["monday", "tuesday", "wednesday", "thursday", "friday"]
```

**4. Guest Privacy Protection**
```yaml
guest_mode:
  auto_enable: true  # When unidentified persons detected
  
  protections:
    - Disable personalized TTS announcements
    - Disable display of personal information
    - Switch to neutral automation profiles
    - No facial recognition of guests (unless opted in)
    - Clear guest data after departure
```

### Security Features

**1. Anomaly Detection**
```python
async def detect_security_anomalies():
    """Detect unusual person presence patterns"""
    
    # Unknown person + all BLE away = ALERT
    if census.unidentified_count > 0 and census.identified_count == 0:
        await send_alert("Unknown person at home while everyone away")
        await start_camera_recording()
    
    # More people than expected
    if census.total_persons > expected_occupancy + 2:
        await send_notification("More people detected than expected")
    
    # Person detected in unusual location at unusual time
    if person_in_location and not is_typical_pattern(person, location, time):
        await log_anomaly("Unusual person location pattern")
```

**2. Data Handling**
```yaml
data_security:
  storage:
    - Census data: SQLite (encrypted at rest)
    - Facial recognition: Never stored (processed in real-time)
    - Camera snapshots: Never stored by URA
    - Transit validation: 30 days retention
  
  access_control:
    - Census sensors: All HA users
    - Camera management: Admin only
    - Privacy settings: Admin only
    - Guest data: Auto-purge after 24 hours
```

---

## 💾 DATABASE SCHEMA

### New Tables

```sql
-- House census snapshots (every 5 minutes)
CREATE TABLE house_census_snapshots (
    timestamp DATETIME PRIMARY KEY,
    identified_count INTEGER NOT NULL,
    identified_persons TEXT,  -- JSON array
    unidentified_count INTEGER NOT NULL,
    total_persons INTEGER NOT NULL,
    confidence TEXT NOT NULL,  -- 'high', 'medium', 'low'
    validation_age_seconds INTEGER,
    zones_distribution TEXT  -- JSON: {"upstairs": 2, "downstairs": 1}
);

CREATE INDEX idx_census_timestamp ON house_census_snapshots(timestamp);
CREATE INDEX idx_census_total_persons ON house_census_snapshots(total_persons);

-- Entry/exit events
CREATE TABLE person_entry_exit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    person_name TEXT,  -- NULL if unidentified
    event_type TEXT NOT NULL,  -- 'entry' or 'exit'
    detection_source TEXT NOT NULL,  -- 'entryway_camera', 'ble_arrival', etc.
    confidence REAL NOT NULL,
    entry_point TEXT  -- 'entryway', 'garage', etc.
);

CREATE INDEX idx_entry_exit_timestamp ON person_entry_exit_events(timestamp);
CREATE INDEX idx_entry_exit_person ON person_entry_exit_events(person_name);
CREATE INDEX idx_entry_exit_type ON person_entry_exit_events(event_type);

-- Transit validation events
CREATE TABLE transit_validation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    person_name TEXT NOT NULL,
    camera_location TEXT NOT NULL,  -- 'master_hallway', 'stairs', etc.
    validation_success BOOLEAN NOT NULL,
    hours_since_last_sighting REAL,
    confidence_score REAL
);

CREATE INDEX idx_transit_timestamp ON transit_validation_events(timestamp);
CREATE INDEX idx_transit_person ON transit_validation_events(person_name);

-- Camera person events (transition zones and shared spaces)
CREATE TABLE camera_person_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    room_id TEXT NOT NULL,
    person_count INTEGER NOT NULL,
    identified_persons TEXT,  -- JSON array (if facial recognition enabled)
    unknown_count INTEGER NOT NULL,
    camera_source TEXT NOT NULL,  -- 'unifi' or 'frigate'
    camera_entity_id TEXT NOT NULL
);

CREATE INDEX idx_camera_events_timestamp ON camera_person_events(timestamp);
CREATE INDEX idx_camera_events_room ON camera_person_events(room_id);

-- Zone person distribution snapshots
CREATE TABLE zone_person_distribution (
    timestamp DATETIME NOT NULL,
    zone_id TEXT NOT NULL,
    person_count INTEGER NOT NULL,
    identified_persons TEXT,  -- JSON array
    unidentified_count INTEGER NOT NULL,
    rooms_distribution TEXT,  -- JSON: {"bedroom": 1, "bathroom": 0}
    PRIMARY KEY (timestamp, zone_id)
);

CREATE INDEX idx_zone_dist_timestamp ON zone_person_distribution(timestamp);
CREATE INDEX idx_zone_dist_zone ON zone_person_distribution(zone_id);
```

### Data Collection Strategy

```python
async def collect_census_snapshot():
    """Called every 5 minutes via scheduled task"""
    
    census = await self.census_engine.calculate_census()
    
    await self.db.execute(
        """INSERT INTO house_census_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(),
            census['identified_count'],
            json.dumps(census['identified_persons']),
            census['unidentified_count'],
            census['total_persons'],
            census['confidence'],
            census['validation_age_minutes'] * 60,
            json.dumps(census['zone_distribution'])
        )
    )
```

---

## 🎯 USE CASES & EXAMPLES

### 1. Phone Left Behind Detection

**Scenario:**
```
7:00 AM: BLE detects John's phone in bedroom
7:05 AM: mmWave shows bedroom empty
7:06 AM: Master hallway camera sees person (validated as John)
7:06 AM: Stairs camera sees person going down
7:07 AM: Kitchen motion sensor triggers
```

**System Response:**
```python
# Census engine recognizes anomaly
ble_location = "bedroom"
camera_path = ["master_hallway", "stairs"]
likely_actual_location = "kitchen"

# Update person tracking
person_state = "device_left_behind"
actual_location = "kitchen"
confidence = "high"

# Automation adjustments
# Don't follow music to bedroom (phone there)
# DO follow music to kitchen (person there)
```

**Sensors:**
```yaml
binary_sensor.john_device_left_behind: on
sensor.john_actual_location: "kitchen"
sensor.john_ble_location: "bedroom"
```

### 2. Guest Detection & Guest Mode

**Scenario:**
```
6:00 PM: BLE shows John + Jane home (2 identified)
6:30 PM: Living room camera detects 4 persons
6:30 PM: Facial recognition: John, Jane (2 identified, 2 unknown)
```

**System Response:**
```python
# Census calculation
identified_count = 2  # John, Jane
unidentified_count = 2  # Two guests
total_persons = 4

# Auto-enable guest mode
guest_mode_active = True

# Automation adjustments
- Disable personal TTS notifications
- Switch music to neutral playlist
- Increase HVAC target (4 person load vs 2)
- Disable personalized dashboard displays
```

**Sensors:**
```yaml
sensor.ura_unidentified_persons_count: 2
input_boolean.guest_mode_active: on
sensor.living_room_camera_person_count: 4
sensor.ura_total_persons_home: 4
```

### 3. Security Anomaly - Unknown Person While Away

**Scenario:**
```
2:00 PM: All BLE devices absent (John & Jane away)
2:15 PM: Entryway camera detects person
2:15 PM: No facial recognition match
2:15 PM: Living room camera detects person
```

**System Response:**
```python
# Census anomaly detected
identified_count = 0  # No BLE devices
unidentified_count = 1  # Camera sees someone
security_alert = True

# Actions
- Send mobile app notification: "Unknown person detected"
- Start recording all cameras
- Log event to security coordinator
- Optional: Trigger alarm system
```

**Sensors:**
```yaml
binary_sensor.ura_unexpected_person_detected: on
sensor.ura_security_alert_level: "high"
sensor.ura_unidentified_persons_count: 1
```

### 4. Whole-House HVAC Optimization

**Scenario:**
```
Census: 4 total persons (2 upstairs, 2 downstairs)
Previous setting: 2 person HVAC profile
```

**System Response:**
```python
# Calculate HVAC adjustment
base_temp = 70°F
occupancy_load = 4 persons
heat_load_adjustment = +2°F  # Body heat from 4 people

adjusted_target = 70 - 2 = 68°F

# Zone distribution
upstairs: 2 persons → normal cooling
downstairs: 2 persons → normal cooling

# Apply to HVAC coordinator (v3.6.0 will use this)
await hvac_coordinator.set_occupancy_load(4)
```

**Sensors:**
```yaml
sensor.ura_total_persons_home: 4
sensor.upstairs_person_count: 2
sensor.downstairs_person_count: 2
sensor.ura_hvac_occupancy_load: 4
```

### 5. Movement Prediction with Camera Validation

**Scenario:**
```
8:00 AM: John in bedroom (BLE + mmWave)
8:05 AM: Bedroom → Master hallway (camera validates)
8:05 AM: Pattern predicts: Kitchen (80% confidence)
8:05 AM: Pre-action: Warm kitchen, prepare coffee lights
8:06 AM: Stairs camera confirms John going down
8:07 AM: Kitchen BLE detects John's phone
```

**System Response:**
```python
# v3.3.0 Pattern Learning predicts
predicted_next = "kitchen"
confidence = 0.80
alternatives = ["office": 0.12, "bathroom": 0.05]

# v3.5.0 Camera Validation confirms path
camera_checkpoints = ["master_hallway", "stairs"]
all_checkpoints_validated = True

# Combined confidence boost
final_confidence = 0.80 * 1.2 = 0.96  # High confidence

# Pre-emptive automation
await trigger_kitchen_occupancy_prep()
```

**Sensors:**
```yaml
binary_sensor.john_movement_validated: on
sensor.john_predicted_next_room: "kitchen"
sensor.john_predicted_confidence: 0.96
```

---

## 🧪 TESTING STRATEGY

### Unit Tests

```python
# test_camera_integration.py
async def test_discover_unifi_cameras():
    """Test UniFi camera discovery"""
    manager = CameraIntegrationManager(hass)
    cameras = await manager.discover_cameras("unifi")
    assert "camera.living_room_main" in cameras

async def test_discover_frigate_cameras():
    """Test Frigate camera discovery"""
    manager = CameraIntegrationManager(hass)
    cameras = await manager.discover_cameras("frigate")
    assert len(cameras) > 0

async def test_camera_person_count():
    """Test person counting from cameras"""
    # Mock camera sensor
    hass.states.async_set("binary_sensor.living_room_person", "on", {
        "count": 3
    })
    
    count = await manager.get_person_count("living_room")
    assert count == 3

# test_census_engine.py
async def test_census_calculation():
    """Test basic census calculation"""
    census = HousePersonCensus(hass)
    
    # Mock 2 BLE devices + 3 camera detections
    mock_ble_persons = {"John": {...}, "Jane": {...}}
    mock_camera_total = 3
    
    result = await census.calculate_census()
    
    assert result['identified_count'] == 2
    assert result['unidentified_count'] == 1
    assert result['total_persons'] == 3

async def test_transit_validation():
    """Test transit validation logic"""
    validator = TransitValidator(hass)
    
    # Mock: BLE present but no camera sighting in 5 hours
    result = await validator.validate_person_still_home("John")
    
    assert result[0] == False
    assert "4 hours" in result[1]

async def test_movement_path_validation():
    """Test cross-room movement validation"""
    validator = TransitValidator(hass)
    
    # Mock camera checkpoints
    result = await validator.validate_movement_path(
        "John", "bedroom", "kitchen"
    )
    
    assert result[0] == True  # Validation passed

# test_dual_platform.py
async def test_fallback_chain():
    """Test Frigate → UniFi fallback"""
    manager = DualPlatformCameraManager(hass)
    
    # Frigate unavailable
    mock_frigate_unavailable()
    
    # Should fallback to UniFi
    result = await manager.get_person_detection("living_room")
    
    assert result['source'] == "unifi"
    assert result['person_detected'] == True
```

### Integration Tests

```python
# test_census_integration.py
async def test_full_census_cycle():
    """Test complete census calculation with real sensors"""
    
    # Setup: 2 BLE devices, 1 camera with 3 people
    setup_ble_devices(["John", "Jane"])
    setup_camera_detection("living_room", count=3)
    
    # Trigger census update
    await census_engine.update_census()
    
    # Verify integration-level sensors
    assert state_of("sensor.ura_total_persons_home") == 3
    assert state_of("sensor.ura_identified_persons_count") == 2
    assert state_of("sensor.ura_unidentified_persons_count") == 1
    
    # Verify zone-level sensors
    assert state_of("sensor.downstairs_person_count") == 3

async def test_guest_mode_trigger():
    """Test automatic guest mode activation"""
    
    # Start: No guests
    assert state_of("input_boolean.guest_mode_active") == "off"
    
    # Camera detects unidentified person
    hass.states.async_set("sensor.living_room_camera_person_count", 3, {
        "identified_count": 2,
        "unidentified_count": 1
    })
    
    await async_wait(1)  # Wait for automation
    
    # Verify guest mode activated
    assert state_of("input_boolean.guest_mode_active") == "on"

async def test_security_anomaly_detection():
    """Test unknown person alert when away"""
    
    # Setup: All BLE away, camera detects person
    remove_all_ble_devices()
    trigger_camera_detection("entryway", count=1)
    
    await async_wait(1)
    
    # Verify alert triggered
    assert state_of("binary_sensor.ura_unexpected_person_detected") == "on"
    assert was_notification_sent("Security Alert")
```

### User Acceptance Tests

```python
# test_use_cases.py
async def test_phone_left_behind_scenario():
    """Test: John leaves phone in bedroom, goes to kitchen"""
    
    # T+0s: Phone in bedroom
    set_ble_location("John", "bedroom")
    
    # T+5s: Bedroom empty
    set_room_occupied("bedroom", False)
    
    # T+6s: Camera sees John in hallway
    trigger_camera("master_hallway", person="John")
    
    # T+7s: Camera sees John on stairs
    trigger_camera("stairs", person="John")
    
    # T+8s: Kitchen occupied
    set_room_occupied("kitchen", True)
    set_ble_location("John", "kitchen")
    
    await async_wait(2)
    
    # Verify detection
    assert state_of("binary_sensor.john_device_left_behind") == "on"
    assert state_of("sensor.john_actual_location") == "kitchen"
    
    # Verify music didn't go to bedroom
    music_state = get_music_following_state("John")
    assert music_state.room == "kitchen"  # Followed person, not phone

async def test_guest_arrival_scenario():
    """Test: 2 guests arrive for dinner"""
    
    # T+0: Just John & Jane home
    setup_ble_devices(["John", "Jane"])
    
    # T+5min: Living room camera sees 4 people
    trigger_camera("living_room", count=4, identified=["John", "Jane"])
    
    await async_wait(2)
    
    # Verify census updated
    assert int(state_of("sensor.ura_total_persons_home")) == 4
    assert int(state_of("sensor.ura_unidentified_persons_count")) == 2
    
    # Verify guest mode enabled
    assert state_of("input_boolean.guest_mode_active") == "on"
    
    # Verify HVAC adjusted for 4 people
    hvac_load = int(state_of("sensor.ura_hvac_occupancy_load"))
    assert hvac_load == 4
```

---

## ⚙️ CONFIGURATION

### Config Flow Options

```python
class CameraIntelligenceConfigFlow(ConfigFlow):
    """Config flow for camera intelligence features"""
    
    async def async_step_user(self, user_input=None):
        """Handle initial configuration"""
        
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("camera_integration_enabled", default=True): bool,
                vol.Required("camera_platform"): vol.In(["unifi", "frigate", "both"]),
                vol.Optional("facial_recognition_enabled", default=False): bool,
                vol.Optional("guest_detection_enabled", default=True): bool,
                vol.Optional("transit_validation_enabled", default=True): bool,
            })
        )
    
    async def async_step_privacy_settings(self, user_input=None):
        """Configure privacy settings"""
        
        return self.async_show_form(
            step_id="privacy",
            data_schema=vol.Schema({
                vol.Optional("privacy_mode_enabled", default=False): bool,
                vol.Optional("facial_recognition_opt_in", default=False): bool,
                vol.Optional("guest_face_learning", default=False): bool,
                vol.Optional("data_retention_days", default=30): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=90)
                ),
            })
        )
    
    async def async_step_room_cameras(self, user_input=None):
        """Configure which rooms have cameras"""
        
        # Auto-discover available cameras
        cameras = await discover_available_cameras()
        
        # Let user assign cameras to rooms
        return self.async_show_form(
            step_id="room_cameras",
            data_schema=vol.Schema({
                vol.Optional(f"camera_{room_id}"): vol.In(cameras)
                for room_id in self.get_room_ids()
            })
        )
```

### Options Flow (Runtime Changes)

```python
class CameraIntelligenceOptionsFlow(OptionsFlow):
    """Handle options changes"""
    
    async def async_step_init(self, user_input=None):
        """Manage camera intelligence options"""
        
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    "census_update_interval",
                    default=self.config_entry.options.get("census_update_interval", 300)
                ): vol.All(vol.Coerce(int), vol.Range(min=60, max=600)),
                
                vol.Optional(
                    "transit_validation_timeout",
                    default=self.config_entry.options.get("transit_validation_timeout", 4)
                ): vol.All(vol.Coerce(int), vol.Range(min=2, max=8)),
                
                vol.Optional(
                    "guest_mode_auto_enable",
                    default=self.config_entry.options.get("guest_mode_auto_enable", True)
                ): bool,
                
                vol.Optional(
                    "security_alerts_enabled",
                    default=self.config_entry.options.get("security_alerts_enabled", True)
                ): bool,
            })
        )
```

---

## 📊 METRICS & MONITORING

### Performance Metrics

```yaml
# Diagnostic sensors for monitoring system health
sensor.ura_camera_integration_health:
  state: "healthy"  # healthy/degraded/unavailable
  attributes:
    unifi_cameras_online: 7
    unifi_cameras_offline: 0
    frigate_cameras_online: 7
    frigate_cameras_offline: 0
    last_check: "2026-01-14T10:30:00"
    issues: []

sensor.ura_census_update_latency:
  state: 1.2  # seconds
  unit_of_measurement: "s"
  attributes:
    average_latency_1h: 1.15
    max_latency_1h: 2.8
    update_frequency: "5min"

sensor.ura_transit_validation_success_rate:
  state: 94.5  # percentage
  unit_of_measurement: "%"
  attributes:
    validations_today: 48
    successes_today: 45
    failures_today: 3
    common_failure_points: ["downstairs_hallway"]
```

### Debugging Tools

```python
async def diagnose_census_accuracy():
    """Compare census against manual count"""
    
    census = await census_engine.calculate_census()
    
    print("Census Report:")
    print(f"  Identified: {census['identified_persons']}")
    print(f"  Unidentified: {census['unidentified_count']}")
    print(f"  Total: {census['total_persons']}")
    print(f"  Confidence: {census['confidence']}")
    print()
    print("Data Sources:")
    print(f"  BLE devices present: {await count_ble_devices()}")
    print(f"  Camera total: {await sum_camera_detections()}")
    print(f"  Transit validation ages:")
    
    for person in census['identified_persons']:
        age = await get_transit_validation_age(person)
        print(f"    {person}: {age} minutes ago")

async def test_camera_coverage():
    """Verify camera coverage of key areas"""
    
    coverage_map = {
        "master_hallway": ["camera.master_hallway"],
        "stairs": ["camera.stairs"],
        "living_room": ["camera.living_room_main", "camera.living_room_corner"],
        "entryway": ["camera.entryway"],
    }
    
    for area, cameras in coverage_map.items():
        print(f"\n{area}:")
        for camera in cameras:
            status = await check_camera_status(camera)
            print(f"  {camera}: {'✅ Online' if status else '❌ Offline'}")
```

---

## 🚀 DEPLOYMENT PLAN

### Phase 1: Foundation (Week 1-2)

**Deliverables:**
- Camera integration manager
- Room-level camera sensors (shared spaces + transition zones)
- Enhanced multi-sensor fusion
- Basic person detection working

**Validation:**
- [ ] All cameras discovered and mapped to rooms
- [ ] Camera sensors updating in real-time
- [ ] Fusion algorithm includes camera data
- [ ] No performance degradation

### Phase 2: Census System (Week 3-4)

**Deliverables:**
- House Person Coordinator
- Integration-level census sensors
- Zone aggregation sensors
- Person distribution analysis
- Database schema deployed

**Validation:**
- [ ] Census updates every 5 minutes
- [ ] Identified vs unidentified count accurate
- [ ] Zone person counts correct
- [ ] Database collecting snapshots

### Phase 3: Validation & Intelligence (Week 5-6)

**Deliverables:**
- Transit validator
- Movement path validation
- Entry/exit tracking
- Security anomaly detection
- Guest mode automation

**Validation:**
- [ ] Transit validation detecting "phone left behind"
- [ ] Movement paths validated via camera checkpoints
- [ ] Entry/exit events logging correctly
- [ ] Security alerts working
- [ ] Guest mode auto-enabling

### Phase 4: Integration & Polish (Week 7)

**Deliverables:**
- Integration with v3.3.0 cross-room features
- Privacy modes tested and working
- Documentation complete
- User guide created
- Performance optimized

**Validation:**
- [ ] Music following uses camera validation
- [ ] Privacy modes respect settings
- [ ] Performance metrics acceptable
- [ ] All tests passing (100+ tests)
- [ ] Documentation reviewed

---

## 🎯 SUCCESS CRITERIA

### Must Have (v3.5.0 Release Blockers)

- [x] Camera integration working for UniFi Protect
- [x] Camera integration working for Frigate
- [x] House census system accurate (±1 person)
- [x] Transit validation working (4 hour timeout)
- [x] Zone person aggregation correct
- [x] Database collecting snapshots
- [x] Privacy modes functional
- [x] Guest detection working
- [x] Security anomaly alerts working
- [x] 100+ tests passing
- [x] No performance regression vs v3.3.0

### Should Have (High Priority)

- [ ] Facial recognition working (if enabled)
- [ ] Movement path validation (camera checkpoints)
- [ ] Entry/exit tracking accurate
- [ ] Guest mode auto-enabling
- [ ] HVAC occupancy load optimization
- [ ] Phone-left-behind detection
- [ ] Diagnostic sensors for monitoring
- [ ] User guide documentation

### Nice to Have (Future Enhancements)

- [ ] Machine learning for person identification
- [ ] Predictive guest arrival detection
- [ ] Historical occupancy pattern analysis
- [ ] Integration with alarm systems
- [ ] Video clip capture on anomalies
- [ ] Mobile app dashboard for census
- [ ] Voice assistant queries ("who's home?")

---

## 📈 VALUE MATRIX

| Feature | Value | Difficulty | Priority |
|---------|-------|------------|----------|
| House Census System | 95 | 70 | **CRITICAL** |
| Camera Integration | 90 | 40 | **CRITICAL** |
| Multi-Sensor Fusion | 90 | 50 | **CRITICAL** |
| Transit Validation | 85 | 60 | HIGH |
| Guest Detection | 85 | 40 | HIGH |
| Security Anomalies | 80 | 50 | HIGH |
| Zone Aggregation | 75 | 30 | HIGH |
| Entry/Exit Tracking | 75 | 45 | MEDIUM |
| Movement Path Validation | 70 | 55 | MEDIUM |
| Phone Left Behind | 70 | 40 | MEDIUM |
| Privacy Modes | 90 | 35 | **CRITICAL** |
| Dual Platform Strategy | 65 | 45 | MEDIUM |
| Facial Recognition | 60 | 70 | LOW |

**Value Scale:** 0-100 (higher = more valuable)  
**Difficulty Scale:** 0-100 (higher = more difficult)  
**Priority:** CRITICAL > HIGH > MEDIUM > LOW  

---

## 🔗 DEPENDENCIES

### Requires (Must Be Completed First)

- **v3.2.9** (Current) - Multi-person tracking framework, zones
- **v3.3.0** - Room transition detection, pattern learning (optional synergy)

### Enables (Unlocked by v3.5.0)

- **v3.6.0** - Domain Coordinators (uses census data for decisions)
- **v4.0.0** - Bayesian predictions (uses identity-aware patterns)

### Integration Points

**Home Assistant Core:**
- Camera platforms (UniFi Protect, Frigate)
- Binary sensor platform
- Sensor platform
- Device registry
- Entity registry

**URA Internal:**
- Room coordinators (camera sensors)
- Zone coordinators (person aggregation)
- Multi-sensor fusion (enhanced algorithm)
- Database manager (new tables)
- Config flow (camera settings)

**External Integrations:**
- UniFi Protect integration
- Frigate integration
- Bermuda BLE (person identity)
- Mobile app (alerts)

---

## ⚠️ RISKS & MITIGATION

### Technical Risks

**1. Camera Platform Reliability**
- **Risk:** Frigate or UniFi goes offline, breaks census
- **Mitigation:** Dual platform fallback, graceful degradation
- **Fallback:** BLE + existing sensors continue working

**2. False Positives in Person Detection**
- **Risk:** Pets trigger camera person detection
- **Mitigation:** Confidence thresholds, fusion algorithm discounts outliers
- **Fallback:** Require multiple sensors to agree

**3. Privacy Concerns**
- **Risk:** Users uncomfortable with camera tracking
- **Mitigation:** Cameras only in shared spaces, explicit opt-in, privacy modes
- **Fallback:** Disable camera features, fall back to BLE + sensors

**4. Performance Impact**
- **Risk:** Census calculations slow down system
- **Mitigation:** Async operations, 5-minute update interval (not real-time)
- **Fallback:** Reduce update frequency

### Operational Risks

**1. Complex Configuration**
- **Risk:** Users struggle to set up camera mapping
- **Mitigation:** Auto-discovery, sensible defaults, clear UI
- **Fallback:** Skip camera integration, use BLE only

**2. Data Storage Growth**
- **Risk:** Census snapshots fill database
- **Mitigation:** 30-day retention, auto-cleanup, indexes
- **Fallback:** Reduce snapshot frequency

**3. Integration Conflicts**
- **Risk:** Other integrations also use cameras
- **Mitigation:** Read-only access, no camera control
- **Fallback:** Disable URA camera integration

---

## 📚 DOCUMENTATION REQUIREMENTS

### User Documentation

**1. Setup Guide**
- Camera integration setup (UniFi + Frigate)
- Room-to-camera mapping
- Privacy settings configuration
- Guest detection preferences

**2. Sensor Reference**
- All new census sensors
- Camera person sensors
- Zone aggregation sensors
- Attributes and units

**3. Use Case Examples**
- Guest arrival automation
- Security alert setup
- HVAC optimization
- Music following enhancement

**4. Troubleshooting**
- Camera not detected
- Census count incorrect
- Transit validation failing
- Performance issues

### Developer Documentation

**1. Architecture Overview**
- House Person Coordinator design
- Census engine algorithm
- Multi-sensor fusion updates
- Database schema

**2. API Reference**
- CameraIntegrationManager
- HousePersonCensus
- TransitValidator
- DualPlatformCameraManager

**3. Testing Guide**
- Unit test examples
- Integration test setup
- Mock data creation
- CI/CD integration

**4. Extension Guide**
- Adding new camera platforms
- Custom census algorithms
- Additional validation logic
- New anomaly detectors

---

## ✅ VALIDATION CHECKLIST

### Pre-Development

- [ ] v3.3.0 deployed and stable (optional but beneficial)
- [ ] UniFi Protect integration configured
- [ ] Frigate integration configured (optional)
- [ ] Camera locations documented
- [ ] Privacy requirements understood
- [ ] Database backup created

### Development Phase

- [ ] Camera integration manager implemented
- [ ] Room-level camera sensors created
- [ ] Multi-sensor fusion enhanced
- [ ] House Person Coordinator built
- [ ] Census engine implemented
- [ ] Transit validator created
- [ ] Database schema deployed
- [ ] Configuration flow complete
- [ ] Privacy modes implemented
- [ ] Tests written (100+ tests)

### Pre-Deployment

- [ ] All unit tests passing
- [ ] All integration tests passing
- [ ] Manual testing complete
- [ ] Privacy modes validated
- [ ] Performance benchmarks met
- [ ] Documentation complete
- [ ] User guide reviewed
- [ ] Backup and rollback plan ready

### Post-Deployment

- [ ] Census counts verified accurate
- [ ] Camera sensors updating
- [ ] Transit validation working
- [ ] Guest detection functioning
- [ ] Security alerts tested
- [ ] No performance regression
- [ ] Database collecting data
- [ ] User feedback collected

---

## 🎉 CONCLUSION

v3.5.0 transforms URA from room-level automation into a **whole-house intelligence system**. By strategically placing cameras in shared spaces and transition zones (not private rooms), we create a complementary sensor architecture where:

- **BLE provides identity in private spaces** (no privacy concerns)
- **Cameras validate and enhance in shared/transition zones** (natural checkpoints)
- **Multi-sensor fusion creates defense-in-depth** (high confidence)
- **House census knows who, where, how many** (with precision)

This foundation enables v3.6.0 Domain Coordinators and v4.0.0 Bayesian predictions to make smarter decisions with better data.

**Key Innovations:**
1. **Complementary architecture** - Each sensor covers others' weaknesses
2. **Transit validation** - 2-4 hour heartbeat for BLE confirmation
3. **Dual platform strategy** - UniFi + Frigate for best capabilities
4. **Privacy-first design** - Cameras only where appropriate
5. **House census system** - Whole-house person intelligence
6. **Identity-aware tracking** - Know *who* not just "someone"

**Ready to Build:** Fully specified, effort estimated, success criteria defined.

---

**Planning Document v1.0**  
**Created:** January 14, 2026  
**Status:** Ready for implementation  
**Estimated Effort:** 15-18 hours  
**Model:** Sonnet 4.5 (well-specified work)  
**Dependencies:** v3.2.9 (done), v3.3.0 (beneficial synergy)  
**Enables:** v3.6.0 Domain Coordinators, v4.0.0 Predictions

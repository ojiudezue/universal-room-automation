# v3.3.0 Planning Context - Cross-Room Coordination

**Version:** v3.3.0  
**Type:** Major Feature Release  
**Effort:** 6-7 hours (REVISED - reduced scope)  
**Timeline:** Q1 2026 (March)  
**Priority:** HIGH  
**Status:** Planning complete (REVISED 2026-01-04), ready to build  
**Revision:** Scope refined - deferred time-of-day/routine detection to v4.0, enhanced multi-step prediction  

---

## 🎯 OVERVIEW

**Theme:** "Rooms talk to each other - the home flows"

**Objective:** Transform URA from isolated room intelligence to coordinated whole-house intelligence where rooms understand and respond to cross-room movement patterns.

**Prerequisites:**
- ✅ v3.2.9 stable and deployed
- ✅ Person tracking working reliably (v3.2.8.3+)
- ⏳ 30+ days of transition data (currently collecting)
- ✅ Event-driven architecture (< 5s response)

**Value Proposition:**
- Natural room-to-room flow (lights/music follow you)
- Predictive preconditioning (next room ready before you arrive)
- Pattern learning (understand your routines)
- Whole-house awareness (zone status influences rooms)

---

## 🎯 v3.3.0 SCOPE CLARIFICATION

**What's IN v3.3.0 (6-7 hours):**
1. ✅ Transition detection + database (2h)
2. ✅ Generic following framework (2h) - Reusable for music/HVAC/fans/purifiers
3. ✅ **Music following implementation** (2h) - KILLER APP for daily use
4. ✅ HVAC zone preset triggers (30min) - Free bonus with existing coordination
5. ✅ **Enhanced pattern learning** (2h):
   - Multi-step path prediction (2-3 rooms ahead)
   - Confidence scoring (sample size adjusted)
   - Alternative predictions (top 3 options)
   - Current path tracking
   - **All-time frequency analysis** (simplified)
6. ✅ Database + sensors (1h)

**What's DEFERRED to v4.0 (adds complexity without proportional value):**
- ❌ Light following (already 90% solved with per-room light definitions)
- ❌ Preconditioning (low ROI - HVAC takes 15+ min to change temp)
- ❌ Time-of-day awareness (morning/evening patterns)
- ❌ Routine detection/classification
- ❌ Full Bayesian inference

**Why This Scope:**
- Music following = daily-use killer app with immediate wow factor
- Light following already mostly solved by existing room automation
- Simple frequency-based pattern learning gets 90% of value with 20% of effort
- Time-based segmentation adds complexity for marginal accuracy gain
- Focus on getting cross-room coordination working first

**Media Player Architecture Notes:**
- Room players: Individual per room (media_player.bedroom)
- Zone players: Can be aggregate OR independent (media_player.zone_upstairs)
- House player: Can be aggregate OR independent (media_player.house)
- **Fallback strategy:** Try zone_player_entity (Sonos group - PREFERRED for quality) → If fails, send to ALL room players in zone (SAFETY NET)

---

## 📊 CURRENT STATE ANALYSIS

### What We Have (v3.2.9)

**Person Tracking:**
- ✅ Room-level location per person
- ✅ Previous location tracking
- ✅ Last seen timestamps
- ✅ Database logging active

**Data Available:**
```sql
-- person_visits table
person_id, location, entered_at, exited_at

-- person_presence_snapshots table  
person_id, location, timestamp, confidence

-- What we're collecting:
- Who is where
- When they entered
- When they left
- Confidence scores
```

**What We're Missing:**
```sql
-- room_transitions table (NEW)
person_id, from_room, to_room, timestamp, 
duration_seconds, path_type
```

### What We Need

**1. Transition Detection**
- When person moves from Room A to Room B
- How long the transition took
- What type of movement (direct, via hallway, etc.)

**2. Pattern Recognition**
- Common paths (bedroom → bathroom → kitchen)
- Time-based patterns (weekday mornings vs weekends)
- Probability of next room

**3. Cross-Room Actions**
- Light following
- Music following
- Preconditioning

---

## 🏗️ ARCHITECTURE DESIGN

### New Components

**1. TransitionDetector** (transitions.py)
```python
class TransitionDetector:
    """Detect and classify room-to-room transitions."""
    
    def __init__(self, hass, person_coordinator):
        self.hass = hass
        self.person_coordinator = person_coordinator
        self._register_listeners()
    
    def _register_listeners(self):
        """Listen for location changes."""
        self.person_coordinator.async_add_listener(
            self._on_location_change
        )
    
    async def _on_location_change(self, person_id, new_location, old_location):
        """Detect transition."""
        
        if old_location == "away" or new_location == "away":
            return  # Skip home/away transitions
        
        # Calculate transition time
        now = dt_util.now()
        last_change = self._get_last_change_time(person_id)
        duration = (now - last_change).total_seconds()
        
        # Classify transition
        transition = self._classify_transition(
            person_id, old_location, new_location, duration
        )
        
        # Log to database
        await self._log_transition(transition)
        
        # Emit event for other components
        self.hass.bus.async_fire(
            "ura_person_transition",
            {
                "person_id": person_id,
                "from_room": old_location,
                "to_room": new_location,
                "duration": duration,
                "type": transition.type
            }
        )
    
    def _classify_transition(self, person_id, from_room, to_room, duration):
        """Classify transition type."""
        
        if duration < 60:
            # Direct transition (< 1 minute)
            return Transition(
                type="direct",
                confidence=0.95
            )
        elif 60 <= duration < 120:
            # Likely via hallway (1-2 minutes)
            hallway = self._infer_intermediate_room(from_room, to_room)
            return Transition(
                type="via_hallway",
                via_room=hallway,
                confidence=0.75
            )
        else:
            # Too long - separate events (> 2 minutes)
            return Transition(
                type="separate",
                confidence=0.50
            )
```

**2. PatternLearner** (pattern_learning.py)
```python
class PatternLearner:
    """Learn movement patterns using frequency-based analysis.
    
    SIMPLIFIED APPROACH (v3.3.0):
    - All-time frequency counting (no time-of-day segmentation)
    - Multi-step path prediction (2-3 rooms ahead)
    - Confidence scoring (sample size adjusted)
    - Alternative predictions (top 3 options)
    
    DEFERRED TO v4.0:
    - Time-of-day awareness
    - Routine detection/classification
    - Bayesian inference
    """
    
    def __init__(self, hass, database):
        self.hass = hass
        self.db = database
    
    async def analyze_patterns(self, person_id, days=30):
        """Analyze last N days of transitions for all-time patterns."""
        
        transitions = await self.db.get_transitions(
            person_id=person_id,
            days=days
        )
        
        # Build frequency map of all transitions (no time segmentation)
        transition_counts = {}
        for trans in transitions:
            key = (trans.from_room, trans.to_room)
            transition_counts[key] = transition_counts.get(key, 0) + 1
        
        # Build multi-step sequences (2-3 rooms)
        sequences = self._build_sequences(transitions, max_length=3)
        
        return {
            "transition_counts": transition_counts,
            "sequences": sequences,
            "total_samples": len(transitions)
        }
    
    def _build_sequences(self, transitions, max_length=3):
        """Build multi-step sequences from transitions."""
        from collections import Counter
        
        sequences = Counter()
        
        # Sliding window over transitions
        for i in range(len(transitions) - max_length + 1):
            window = transitions[i:i + max_length]
            
            # Extract room sequence
            seq = [window[0].from_room] + [t.to_room for t in window]
            sequences[tuple(seq)] += 1
        
        return dict(sequences)
    
    def predict_next_room(self, person_id, current_room):
        """Predict next room(s) with multi-step lookahead.
        
        Returns:
            {
                "next_room": "Bathroom",
                "confidence": 0.73,
                "sample_size": 34,
                "reliability": "high",  # Based on sample size
                "alternatives": [
                    {"room": "Kitchen", "confidence": 0.15},
                    {"room": "Office", "confidence": 0.08}
                ],
                "predicted_path": ["Bathroom", "Kitchen"]  # Multi-step
            }
        """
        patterns = self._get_patterns(person_id)
        
        # Find all transitions from current room
        predictions = {}
        sample_sizes = {}
        
        for (from_room, to_room), count in patterns["transition_counts"].items():
            if from_room == current_room:
                predictions[to_room] = predictions.get(to_room, 0) + count
                sample_sizes[to_room] = sample_sizes.get(to_room, 0) + count
        
        # Normalize to probabilities
        total = sum(predictions.values())
        if total == 0:
            return None
        
        probabilities = {
            room: count / total 
            for room, count in predictions.items()
        }
        
        # Sort by probability
        sorted_predictions = sorted(
            probabilities.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        
        if not sorted_predictions:
            return None
        
        # Primary prediction
        next_room, confidence = sorted_predictions[0]
        sample_size = sample_sizes[next_room]
        
        # Calculate reliability based on sample size
        reliability = self._calculate_reliability(sample_size)
        
        # Alternative predictions (top 3)
        alternatives = [
            {"room": room, "confidence": conf}
            for room, conf in sorted_predictions[1:4]  # Next 3
        ]
        
        # Multi-step prediction (predict path 2-3 rooms ahead)
        predicted_path = self._predict_multi_step(
            person_id, 
            current_room, 
            patterns,
            steps=2
        )
        
        return {
            "next_room": next_room,
            "confidence": confidence,
            "sample_size": sample_size,
            "reliability": reliability,
            "alternatives": alternatives,
            "predicted_path": predicted_path
        }
    
    def _calculate_reliability(self, sample_size):
        """Calculate reliability rating based on sample size."""
        if sample_size >= 20:
            return "high"
        elif sample_size >= 10:
            return "medium"
        elif sample_size >= 5:
            return "low"
        else:
            return "very_low"
    
    def _predict_multi_step(self, person_id, current_room, patterns, steps=2):
        """Predict likely path for next N steps.
        
        Example: Current = "Bedroom"
        Returns: ["Bathroom", "Kitchen"] (most likely 2-step path)
        """
        path = []
        room = current_room
        
        for _ in range(steps):
            # Find most likely next room
            next_predictions = {}
            
            for (from_room, to_room), count in patterns["transition_counts"].items():
                if from_room == room:
                    next_predictions[to_room] = next_predictions.get(to_room, 0) + count
            
            if not next_predictions:
                break
            
            # Get highest probability room
            next_room = max(next_predictions.items(), key=lambda x: x[1])[0]
            path.append(next_room)
            room = next_room
        
        return path
```

**3. LightFollowing** (light_following.py)
```python
class LightFollowing:
    """Seamless light following between rooms."""
    
    def __init__(self, hass, config):
        self.hass = hass
        self.config = config
        self.enabled = config.get("light_following_enabled", True)
    
    async def setup(self):
        """Register for transition events."""
        self.hass.bus.async_listen(
            "ura_person_transition",
            self._on_person_transition
        )
    
    async def _on_person_transition(self, event):
        """Handle person transition."""
        
        if not self.enabled:
            return
        
        person_id = event.data["person_id"]
        from_room = event.data["from_room"]
        to_room = event.data["to_room"]
        
        # Turn on lights in destination
        await self._turn_on_destination_lights(to_room, person_id)
        
        # Wait for person to settle
        await asyncio.sleep(30)
        
        # Turn off lights in source if unoccupied
        if not await self._is_room_occupied(from_room):
            await self._turn_off_source_lights(from_room)
    
    async def _turn_on_destination_lights(self, room, person_id):
        """Turn on lights in destination room."""
        
        # Get room coordinator
        room_coordinator = self._get_room_coordinator(room)
        if not room_coordinator:
            return
        
        # Get room automation config
        automation = room_coordinator.automation
        light_entities = automation.light_entities
        
        if not light_entities:
            return
        
        # Get preferred brightness for person
        brightness_pct = self._get_person_preference(
            person_id, "light_brightness", default=75
        )
        
        # Turn on lights
        await self.hass.services.async_call(
            "light",
            "turn_on",
            {
                "entity_id": light_entities,
                "brightness_pct": brightness_pct
            }
        )
    
    async def _is_room_occupied(self, room):
        """Check if room still has people."""
        room_coordinator = self._get_room_coordinator(room)
        if not room_coordinator:
            return False
        
        return room_coordinator.data.get("occupied", False)
```

**4. MusicFollowing** (music_following.py)
```python
class MusicFollowing:
    """Framework for audio following between rooms."""
    
    # Similar structure to LightFollowing
    # Transfers media playback on room transition
    # Maintains position, volume
    # Fades out source room
    
    async def _on_person_transition(self, event):
        from_player = f"media_player.{event.data['from_room']}"
        to_player = f"media_player.{event.data['to_room']}"
        
        # Check if source is playing
        source_state = self.hass.states.get(from_player)
        if source_state and source_state.state == "playing":
            # Transfer playback
            await self._transfer_media(
                from_player, to_player,
                maintain_position=True
            )
```

**5. ZoneStatusReporter** (zone_status.py)
```python
class ZoneStatusReporter:
    """Report zone-level status to rooms."""
    
    def get_zone_status(self, zone_id):
        """Get current zone status."""
        
        # Aggregate from zone coordinator
        zone_coordinator = self._get_zone_coordinator(zone_id)
        
        return {
            "any_room_occupied": zone_coordinator.data.get("occupied"),
            "total_occupants": zone_coordinator.data.get("occupant_count"),
            "active_rooms": self._get_occupied_rooms(zone_id),
            "average_temperature": self._calc_avg_temp(zone_id),
            "total_power": self._calc_total_power(zone_id),
            "security_status": self._get_security_mode()
        }
```

### Database Changes

**New Table: room_transitions**
```sql
CREATE TABLE IF NOT EXISTS room_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id TEXT NOT NULL,
    from_room TEXT NOT NULL,
    to_room TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    duration_seconds INTEGER NOT NULL,
    path_type TEXT NOT NULL,  -- direct, via_hallway, separate
    confidence REAL,
    via_room TEXT,  -- For via_hallway type
    FOREIGN KEY (person_id) REFERENCES persons(id)
)

CREATE INDEX idx_transitions_person 
ON room_transitions(person_id, timestamp DESC)

CREATE INDEX idx_transitions_rooms
ON room_transitions(from_room, to_room, timestamp DESC)
```

**Database Methods:**
```python
# database.py additions

async def log_room_transition(self, transition_data):
    """Log a room transition."""
    query = """
        INSERT INTO room_transitions 
        (person_id, from_room, to_room, timestamp, 
         duration_seconds, path_type, confidence, via_room)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    await self.execute(query, transition_data)

async def get_transitions(self, person_id, days=30):
    """Get transitions for analysis."""
    query = """
        SELECT * FROM room_transitions
        WHERE person_id = ?
          AND timestamp >= datetime('now', '-{} days')
        ORDER BY timestamp ASC
    """.format(days)
    return await self.fetch_all(query, (person_id,))

async def get_common_paths(self, person_id, time_window=None):
    """Get most common paths."""
    # Group by from_room → to_room
    # Count occurrences
    # Return top 10
```

### New Sensors

**Per Person:**
```python
# sensor.py additions

class PersonLikelyNextRoomSensor(CoordinatorEntity, SensorEntity):
    """Predicted next room for person (simplified v3.3.0 - no time-of-day)."""
    
    @property
    def native_value(self):
        prediction = self.pattern_learner.predict_next_room(
            self._person_id,
            current_room=self._get_current_room()
        )
        
        if prediction:
            return prediction["next_room"]
        return None
    
    @property
    def extra_state_attributes(self):
        prediction = self.pattern_learner.predict_next_room(
            self._person_id,
            current_room=self._get_current_room()
        )
        
        if not prediction:
            return {}
        
        return {
            "confidence": prediction["confidence"],
            "sample_size": prediction["sample_size"],
            "reliability": prediction["reliability"],
            "alternatives": prediction["alternatives"],
            "predicted_path": prediction["predicted_path"]
        }

class PersonCurrentPathSensor(CoordinatorEntity, SensorEntity):
    """Current movement path (last 3-4 rooms)."""
    
    @property
    def native_value(self):
        # Get last 3-4 rooms visited
        recent = self._get_recent_rooms(count=4)
        return " → ".join(recent)
    
    @property
    def extra_state_attributes(self):
        """Return whether current path matches common sequences."""
        current_path = self.native_value
        patterns = self.pattern_learner._get_patterns(self._person_id)
        
        # Check if current path is in top sequences
        matches_common = False
        for seq, count in patterns.get("sequences", {}).items():
            if current_path in " → ".join(seq):
                matches_common = True
                break
        
        return {
            "matches_common_sequence": matches_common,
            "path_length": len(self._get_recent_rooms(count=4))
        }
```

---

## 📋 IMPLEMENTATION PLAN

### Phase 1: Foundation (2-3 hours)

**Files to Create:**
1. `transitions.py` - TransitionDetector class
2. `pattern_learning.py` - PatternLearner class
3. `light_following.py` - LightFollowing class
4. `music_following.py` - MusicFollowing framework

**Files to Modify:**
1. `database.py` - Add room_transitions table and methods
2. `person_coordinator.py` - Emit transition events
3. `__init__.py` - Initialize new components
4. `const.py` - Add configuration constants

**Database Migration:**
```python
# database.py
async def _migrate_to_v4(self):
    """Add room_transitions table."""
    await self.execute(CREATE_TRANSITIONS_TABLE)
    await self.execute(CREATE_TRANSITIONS_INDEXES)
```

### Phase 2: Transition Detection (2-3 hours)

**TransitionDetector Implementation:**
1. Listen for person location changes
2. Calculate transition duration
3. Classify transition type
4. Log to database
5. Emit transition events

**Testing:**
```python
# test_transitions.py

async def test_direct_transition():
    """Test < 60s transition classified as direct."""
    detector = TransitionDetector(hass, person_coordinator)
    
    # Simulate location change after 30s
    transition = detector._classify_transition(
        "person_1", "bedroom", "bathroom", duration=30
    )
    
    assert transition.type == "direct"
    assert transition.confidence > 0.9

async def test_via_hallway_transition():
    """Test 60-120s transition classified as via_hallway."""
    transition = detector._classify_transition(
        "person_1", "bedroom", "kitchen", duration=90
    )
    
    assert transition.type == "via_hallway"
    assert transition.via_room is not None
```

### Phase 3: Pattern Learning (2-3 hours)

**PatternLearner Implementation:**
1. Query transitions from database
2. Group by time windows
3. Detect common sequences
4. Calculate confidence scores
5. Predict next rooms

**Testing:**
```python
# test_pattern_learning.py

async def test_morning_pattern_detection():
    """Test detection of morning routine."""
    
    # Insert 30 days of consistent morning pattern
    for day in range(30):
        await insert_transitions([
            ("bedroom", "bathroom", "07:00"),
            ("bathroom", "kitchen", "07:15"),
            ("kitchen", "garage", "07:45")
        ])
    
    learner = PatternLearner(hass, db)
    patterns = await learner.analyze_patterns("person_1", days=30)
    
    assert "morning_weekday" in patterns
    assert patterns["morning_weekday"]["sequence"] == [
        "bedroom", "bathroom", "kitchen", "garage"
    ]
    assert patterns["morning_weekday"]["confidence"] > 0.8

async def test_next_room_prediction():
    """Test next room prediction."""
    predictions = learner.predict_next_room(
        "person_1",
        current_room="bathroom",
        time_of_day=7
    )
    
    assert predictions[0][0] == "kitchen"  # Most likely
    assert predictions[0][1] > 0.7  # High confidence
```

### Phase 4: Light Following (1-2 hours)

**LightFollowing Implementation:**
1. Listen for transition events
2. Turn on destination lights
3. Wait for person to settle
4. Turn off source if unoccupied

**Testing:**
```python
# test_light_following.py

async def test_light_following():
    """Test lights follow person."""
    
    # Enable light following
    config = {"light_following_enabled": True}
    following = LightFollowing(hass, config)
    await following.setup()
    
    # Simulate transition
    hass.bus.async_fire("ura_person_transition", {
        "person_id": "person_1",
        "from_room": "bedroom",
        "to_room": "bathroom"
    })
    
    await hass.async_block_till_done()
    
    # Check bathroom lights on
    bathroom_state = hass.states.get("light.bathroom")
    assert bathroom_state.state == "on"
    
    # Wait for timeout
    await asyncio.sleep(31)
    
    # Check bedroom lights off (if unoccupied)
    bedroom_state = hass.states.get("light.bedroom")
    assert bedroom_state.state == "off"
```

### Phase 5: Sensors & Integration (1-2 hours)

**New Sensors:**
1. sensor.person_{name}_likely_next_room
2. sensor.person_{name}_routine_type
3. sensor.person_{name}_current_path
4. binary_sensor.person_{name}_routine_active

**Integration:**
1. Add to sensor.py
2. Register with coordinator
3. Update on transitions
4. Test all sensors

---

## 🧪 TESTING STRATEGY

### Unit Tests

**test_transitions.py:**
- Direct transition classification
- Via hallway classification
- Separate event classification
- Transition logging
- Event emission

**test_pattern_learning.py:**
- Pattern detection (morning/evening)
- Sequence extraction
- Confidence calculation
- Next room prediction
- Time window grouping

**test_light_following.py:**
- Light turn-on on transition
- Light turn-off after timeout
- Multi-person scenarios
- Enable/disable toggle

**test_sensors.py:**
- Likely next room sensor
- Routine type sensor
- Current path sensor
- Routine active binary sensor

### Integration Tests

**test_cross_room_integration.py:**
```python
async def test_full_morning_routine():
    """Test complete morning routine flow."""
    
    # Setup: 30 days of data
    # Simulate: Morning routine
    # Verify:
    #   - Transitions detected
    #   - Pattern learned
    #   - Next room predicted
    #   - Lights followed
    #   - Sensors updated
```

### Manual Testing Checklist

- [ ] Walk from bedroom → bathroom (lights follow)
- [ ] Walk from bathroom → kitchen (prediction works)
- [ ] Music playing → Walk to next room (audio follows)
- [ ] Check sensor.likely_next_room (shows prediction)
- [ ] Check sensor.routine_type (detects routine)
- [ ] Check sensor.current_path (shows path)
- [ ] Verify database logging (transitions recorded)

---

## 📊 SUCCESS CRITERIA

### Functional Requirements
- [ ] Transitions detected within 15 seconds
- [ ] Patterns learned after 30 days of data
- [ ] Next room predictions > 70% accurate
- [ ] Light following works seamlessly
- [ ] Music framework functional
- [ ] Zone status available to rooms

### Performance Requirements
- [ ] Transition detection < 5 seconds
- [ ] Pattern analysis < 1 second
- [ ] Database queries < 100ms
- [ ] Light control < 2 seconds
- [ ] No impact on existing automation

### Quality Requirements
- [ ] All 180+ existing tests still pass
- [ ] 20+ new tests for cross-room features
- [ ] Zero syntax errors
- [ ] Backward compatible
- [ ] Documentation complete

---

## 🎯 CONFIGURATION

### New Config Options

**Integration Level:**
```python
CONF_LIGHT_FOLLOWING_ENABLED = "light_following_enabled"
CONF_MUSIC_FOLLOWING_ENABLED = "music_following_enabled"
CONF_PATTERN_LEARNING_DAYS = "pattern_learning_days"  # Default: 30
CONF_TRANSITION_TIMEOUT = "transition_timeout"  # Default: 30s
```

**Room Level:**
```python
CONF_LIGHT_FOLLOWING_BRIGHTNESS = "light_following_brightness_pct"
CONF_PRECONDITIONING_ENABLED = "preconditioning_enabled"
CONF_PRECONDITIONING_TEMP_DELTA = "preconditioning_temp_delta"
```

### Config Flow Updates

**New Step: Cross-Room Features**
```python
async def async_step_cross_room(self, user_input=None):
    """Configure cross-room coordination."""
    
    schema = vol.Schema({
        vol.Required(
            CONF_LIGHT_FOLLOWING_ENABLED,
            default=True
        ): bool,
        vol.Required(
            CONF_MUSIC_FOLLOWING_ENABLED,
            default=False
        ): bool,
        vol.Optional(
            CONF_PATTERN_LEARNING_DAYS,
            default=30
        ): vol.All(vol.Coerce(int), vol.Range(min=7, max=90)),
        vol.Optional(
            CONF_TRANSITION_TIMEOUT,
            default=30
        ): vol.All(vol.Coerce(int), vol.Range(min=10, max=120))
    })
```

---

## 📝 DOCUMENTATION REQUIREMENTS

### User Documentation

**README Updates:**
- Cross-room coordination overview
- Light following explanation
- Music following setup
- Pattern learning description
- Configuration options

**Examples:**
```markdown
## Light Following

When you move from room to room, URA can automatically:
- Turn on lights in the room you're entering
- Turn off lights in the room you left (after 30s if unoccupied)

**Setup:**
1. Settings → Integrations → URA → Configure
2. Enable "Light Following"
3. (Optional) Adjust brightness preference per room

**Example:**
Walk from bedroom → bathroom at 7 AM:
- Bathroom lights turn on at 75% brightness
- After 30 seconds, bedroom lights turn off (if unoccupied)
```

### Developer Documentation

**Architecture Diagrams:**
- Transition detection flow
- Pattern learning pipeline
- Light following sequence
- Database schema

**API Documentation:**
```python
class TransitionDetector:
    """Detect and classify room-to-room transitions.
    
    Listens for person location changes and determines:
    - Transition type (direct, via_hallway, separate)
    - Duration
    - Confidence level
    
    Emits 'ura_person_transition' events for other components.
    """
```

---

## ⚡ PERFORMANCE CONSIDERATIONS

### Database Optimization

**Indexing:**
```sql
-- Essential for pattern queries
CREATE INDEX idx_transitions_person_time
ON room_transitions(person_id, timestamp DESC)

-- Essential for path analysis
CREATE INDEX idx_transitions_rooms_time
ON room_transitions(from_room, to_room, timestamp DESC)
```

**Data Retention:**
```python
# Auto-purge old transitions (> 90 days)
async def _purge_old_transitions(self):
    query = """
        DELETE FROM room_transitions
        WHERE timestamp < datetime('now', '-90 days')
    """
    await self.execute(query)
```

### Memory Optimization

**Pattern Caching:**
```python
# Cache learned patterns (recalculate daily)
self._pattern_cache = {}
self._cache_timestamp = None

async def get_patterns(self, person_id):
    if self._should_refresh_cache():
        self._pattern_cache = await self._learn_patterns()
        self._cache_timestamp = dt_util.now()
    
    return self._pattern_cache.get(person_id)
```

### Event Throttling

**Prevent Spam:**
```python
# Don't emit transitions more than once per 10 seconds
self._last_transition_time = {}

if (now - self._last_transition_time.get(person_id, 0)) < 10:
    return  # Too soon, skip
```

---

## 🚨 RISK MITIGATION

### Potential Issues

**1. False Transition Detection**
- **Risk:** Person lingers in doorway, triggers multiple transitions
- **Mitigation:** 10-second cooldown per person
- **Testing:** Simulate rapid room changes

**2. Light Flickering**
- **Risk:** Rapid transitions cause lights to turn on/off repeatedly
- **Mitigation:** 30-second settle time before turning off
- **Testing:** Walk back and forth between rooms

**3. Music Interruption**
- **Risk:** Audio cuts out during transfer
- **Mitigation:** Preload destination, fade smoothly
- **Testing:** Play music during transitions

**4. Privacy Concerns**
- **Risk:** Users uncomfortable with detailed tracking
- **Mitigation:** Opt-in feature, clear data retention policy
- **Testing:** Ensure disable works completely

**5. Database Growth**
- **Risk:** Transitions table grows unbounded
- **Mitigation:** Auto-purge after 90 days
- **Testing:** Monitor database size

---

## 🎉 DEPLOYMENT PLAN

### Pre-Release
1. Collect 30 days of transition data (already happening)
2. Complete all development (6-7 hours)
3. Run full test suite (200+ tests)
4. Documentation complete
5. User guide ready

### Release
1. Deploy to test environment
2. Monitor for 7 days
3. Verify no regressions
4. Collect user feedback
5. Deploy to production

### Post-Release
1. Monitor pattern learning accuracy
2. Measure light following success rate
3. Collect user feedback
4. Plan v3.3.1 improvements if needed

---

## 📈 METRICS TO TRACK

### Development Metrics
- [ ] Code written: ~1200 lines (reduced scope)
- [ ] Tests added: ~300 lines
- [ ] Test coverage maintained > 90%
- [ ] Build time: 6-7 hours
- [ ] Zero syntax errors

### User Metrics
- [ ] Light following adoption rate
- [ ] Pattern detection accuracy
- [ ] User satisfaction score
- [ ] Feature enable/disable rate
- [ ] Bug reports (target: < 5 in first month)

### Technical Metrics
- [ ] Transition detection time
- [ ] Pattern learning execution time
- [ ] Database query performance
- [ ] Memory usage impact
- [ ] CPU usage impact

---

## 🎯 NEXT STEPS (After v3.3.0)

### v3.3.1 - Refinements (if needed)
- Improve prediction accuracy
- Add more pattern types
- Enhanced music following
- User-requested features

### v3.4.0 - AI Custom Automation
- Natural language room customization
- Claude API integration
- Structured rule execution
- Ultimate flexibility

### v3.6.0 - Domain Coordinators
- Security coordinator
- Energy coordinator
- Comfort coordinator
- HVAC coordinator

---

**Planning Document v2.0 (REVISED)**  
**Created:** January 4, 2026  
**Revised:** January 4, 2026  
**Changes:** Reduced scope (6-7h), simplified pattern learning, enhanced multi-step prediction  
**Ready to Build:** After 30 days of data OR immediately (data collection ongoing)  
**Expected Start:** March 2026 or earlier  
**Owner:** Oji + Claude collaboration

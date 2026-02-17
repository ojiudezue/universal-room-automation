# Universal Room Automation - Vision Document v7

**Version:** 7.0 (Post-v3.2.9)  
**Current Production:** v3.2.9  
**Last Updated:** January 4, 2026  
**Status:** Active development - v3.3.0 next major milestone  

---

## 🎯 EXECUTIVE VISION

**Universal Room Automation** transforms individual rooms into intelligent, self-managing spaces that collectively form a whole-house intelligence system. Rather than scattered automations and blueprints, each room becomes a node in a coordinated network.

**Current Achievement:** Production-ready integration with 74+ entities per room, event-driven automation (2-5s response), zone-based architecture, and robust person tracking framework.

**Future Direction:** Cross-room coordination, natural language customization, domain-level intelligence, and Bayesian predictive analytics.

---

## 📊 CURRENT STATE (v3.2.9)

### Production Capabilities

**Entities per Room:** 74+ (37 base + person tracking + diagnostic)
- Core monitoring: occupancy, temperature, humidity, illuminance, power
- Person tracking: current occupants, count, last seen, previous location
- Predictions: placeholders for Phase 2-4 algorithms
- Diagnostics: automation state, confidence scores, tracking status

**Response Time:** 2-5 seconds (event-driven architecture)
- Event listeners registered at coordinator initialization
- State changes trigger immediate automation evaluation
- No polling delays for critical automations

**Architecture:** Tri-level with explicit zones
```
Integration Entry (Global Config)
├── Zone Entries (Explicit groupings)
│   ├── Zone sensors (4 person tracking per zone)
│   └── Room Entries (Children)
│       └── 74+ entities per room
```

**Data Collection:** SQLite database with structured logging
- Person visits and transitions
- Occupancy snapshots (5-minute intervals)
- Sensor state history
- Energy consumption tracking

**Test Coverage:** 178+ passing tests
- Unit tests for all sensor types
- Integration tests for automation logic
- Person tracking scenarios
- Regression prevention suite

### Recent Achievements (v3.2.8-3.2.9)

**v3.2.9 - Infrastructure Fixes** (January 2026)
- ✅ Zone race condition resolved with deferred initialization
- ✅ Temperature fans support both fan.* and switch.* domains
- ✅ 5-15 second auto-recovery for zone sensors on startup
- ✅ Per-entity domain checking for mixed device types

**v3.2.8.3 - Real-Time Person Tracking** (January 2026)
- ✅ Person sensors update in 1-2 seconds (not 30s polling)
- ✅ Previous location timestamp fixed (records exit time, not entry)
- ✅ Consistent zone sensor naming ("Identified People")

**v3.2.8.2 - Multi-Domain Expansion** (January 2026)
- ✅ Auto/manual devices support lights, fans, switches, input_booleans
- ✅ Humidity fans support both fan.* and switch.* domains

**v3.2.0-3.2.7 - Person Tracking Foundation** (December 2025)
- ✅ Bermuda BLE integration framework
- ✅ Multi-person location tracking
- ✅ Room/zone/integration person sensors
- ✅ Confidence scoring system
- ✅ Database logging for transitions

---

## 🎓 CORE PRINCIPLES

### Technical Excellence
- **Zero tolerance for syntax errors** - Always validate before deploy
- **Test-first mindset** - 178+ tests prevent regressions
- **One-shot development** - Get it right first time
- **Backward compatibility** - Migrations must be seamless
- **Event-driven architecture** - Sub-5-second response times

### Data Philosophy
- **Collect early** - Can't get historical data later
- **Simple schema** - SQLite, not complex graphs
- **Let patterns emerge** - Don't hardcode thresholds
- **Bayesian over ML** - Probability math, not neural networks

### Automation Philosophy
- **Livable automations** - Proper hysteresis, no flickering
- **Fail-safe defaults** - When in doubt, do less
- **User override respected** - Manual actions honored
- **Sleep protection** - Different rules during sleep hours
- **Visual feedback** - Alert lights for important events

### Quality Standards
- **Read quality context before building** - Prevent regressions
- **Run tests before every deployment** - No exceptions
- **Document all learnings** - Build institutional knowledge
- **Systematic validation** - Checklists prevent mistakes
- **Quality over speed** - Rush creates cascades

---

## 🏗️ ARCHITECTURE EVOLUTION

### Current Architecture (v3.2.9)

**Entry Type System:**
```python
ENTRY_TYPE_INTEGRATION = "integration"  # Global config
ENTRY_TYPE_ZONE = "zone"                # Zone grouping  
ENTRY_TYPE_ROOM = "room"                # Room automation
```

**Coordinator Pattern:**
```python
UniversalRoomCoordinator     # Per-room state (30s updates)
PersonTrackingCoordinator    # BLE locations (15s updates)
AggregationCoordinator       # Whole-house sensors
```

**Event-Driven Flow:**
```
State Change Event
  ↓ (< 1 second)
Coordinator Event Listener
  ↓
Automation Logic Evaluation
  ↓
Service Calls (lights, climate, etc)
  ↓
Database Logging
```

**Config Storage Pattern:**
```python
# ALWAYS merge both sources
config = {**entry.data, **entry.options}
# entry.data = initial setup
# entry.options = user changes via Configure
```

### Future Architecture (v3.3+)

**Phase 1: Cross-Room Coordination** (v3.3.0)
```python
TransitionCoordinator        # Room-to-room movement detection
PatternLearner              # Daily routine identification
LightFollowing              # Seamless room transitions
MusicFollowing              # Audio continuity
```

**Phase 2: AI-Powered Customization** (v3.4.0)
```python
CustomAutomationParser      # Claude API natural language → rules
CustomAutomationEngine      # Runtime rule execution
TemplateValidator          # Safe sandboxed evaluation
```

**Phase 3: Domain Coordinators** (v3.6.0)
```python
SecurityCoordinator         # Whole-house security intelligence
EnergyCoordinator          # Energy optimization
ComfortCoordinator         # Multi-zone comfort scoring
HVACCoordinator            # HVAC conflict resolution
```

**Phase 4: Predictive Intelligence** (v4.0.0)
```python
RoutineDetector            # Bayesian pattern detection
OccupancyPredictor         # Probability-based forecasting
EnergyForecast             # Consumption predictions
AnomalyDetector            # Unusual pattern detection
```

---

## 🚀 FEATURE ROADMAP

### Immediate (Q1 2026)

**v3.3.0 - Cross-Room Coordination** (8-10 hours)
- Room transition detection and logging
- Adjacent room preconditioning
- Light following between rooms
- Music following framework
- Movement pattern learning (30-day history)
- Zone status reporting to rooms

**Key Capabilities:**
```python
# Detect transitions
bedroom → bathroom → kitchen (95% confidence, 7:00-8:00 AM)

# Predict next room
if in_bathroom at 7:15 AM:
    preheat_kitchen()  # 85% probability next

# Follow with lights
person_transitions(from="bedroom", to="bathroom")
  → turn_on_lights(bathroom, brightness=50%)
  → wait(30s)
  → if not occupied(bedroom):
       turn_off_lights(bedroom)

# Pattern learning
analyze_last_30_days()
  → morning_pattern = [bedroom→bathroom→kitchen→garage]
  → confidence = 85%
```

### Near-Term (Q2 2026)

**v3.4.0 - AI-Powered Custom Automation** (12-15 hours) ⭐
- Natural language room customization
- Claude API parsing (one-time, config time)
- Structured rule execution (runtime, no AI cost)
- Sandboxed template evaluation
- Graceful fallback to standard automation

**Revolutionary Feature:**
```
User writes in plain English:
"Use sensor.bed_pressure for occupancy.
When TV is on, don't turn off lights.
If CO2 > 1000, turn on air purifier.
Keep lights at 30% after 10 PM."

Claude API parses once → Structured rules → Cache forever

Runtime execution:
Standard Automation (base layer - always runs)
  ↓
Custom Rules Layer (optional enhancement)
  ↓
Final Behavior
```

**Why This Matters:**
- ✅ Every room has unique quirks
- ✅ No code changes needed
- ✅ No version deployments
- ✅ No risk to other rooms
- ✅ Self-documenting in config
- ✅ Future-proof (works with any device)

### Mid-Term (Q3-Q4 2026)

**v3.6.0 - Domain Coordinators** (15-20 hours)
- Security Coordinator (anomaly detection, mode management)
- Energy Coordinator (load optimization, TOU awareness)
- Comfort Coordinator (whole-house scoring, optimization)
- HVAC Coordinator (zone conflict resolution, efficiency)

**Whole-House Intelligence:**
```python
# Security example
if door_opens at 3_AM and everyone_asleep:
    alert_type = "high_severity"
    flash_alert_lights()
    send_notification()

# Energy example  
if battery < 20% and grid_rate > $0.30/kWh:
    mode = "conservation"
    shed_loads = ["pool_pump", "ev_charger"]
    prioritize = ["refrigerator", "hvac", "internet"]

# Comfort example
room_scores = calculate_all_rooms()
worst_room = identify_bottleneck()
recommend_hvac_adjustment()

# HVAC example
if upstairs_wants_heat and downstairs_wants_cool:
    mode = "fan_only"  # Conflict resolution
    adjust_zone_dampers()
```

### Long-Term (2027+)

**v4.0.0 - Bayesian Predictive Intelligence** (20-30 hours)
- Routine detection and prediction (> 80% accuracy)
- Occupancy forecasting with confidence intervals
- Energy consumption prediction
- Anomaly detection and classification
- Multi-objective optimization (comfort vs cost vs energy)

**Math-Based Predictions:**
```python
# Bayesian inference, NOT neural networks
P(next_room | current_room, time, day_type)

# Example: Predict bedroom occupancy at 7 AM
Prior: Historical 60% at 7 AM
Likelihood: Person just left bathroom (85% correlation)
Posterior: 73% probability bedroom occupied

# Explainable, uncertainty-quantified, low-compute
```

**v4.5.0 - 2D Visual Mapping** (30-40 hours)
- Floor plan upload and calibration
- Real-time room state overlays
- Device positioning and status
- Person tracking visualization
- Music flow animations
- Heatmaps (occupancy, energy, patterns)

**Visual Intelligence:**
```javascript
// Interactive floor plan
<FloorPlan image="first_floor.png">
  <Room id="bedroom" occupied={true} temp={72}/>
  <Device id="light.bedroom" state="on" position={[150,100]}/>
  <Person id="Oji" position="bedroom" avatar={...}/>
  <MusicFlow from="bedroom" to="bathroom" animate/>
</FloorPlan>
```

---

## 💡 KEY INNOVATIONS

### 1. Tri-Level Architecture

**Why It's Better:**
```
Single-Entry (OLD):
  Room → All config in one entry
  Problem: No global sharing, no zones

Dual-Entry (v3.0):
  Integration → Rooms
  Better: Global config, but no zones

Tri-Level (v3.1+):
  Integration → Zones → Rooms
  Best: Global config + zone grouping + room autonomy
```

### 2. Event-Driven Coordination

**Why It's Faster:**
```
Polling (OLD):
  Check state every 30 seconds
  Result: 10-30s delays

Event-Driven (v3.2.0.9):
  Listen for state changes
  Result: 2-5s response time
```

### 3. Config Storage Pattern

**Why It's Reliable:**
```
entry.data = Initial setup (immutable)
entry.options = User changes (via Configure)
Merged config = {**data, **options}

Result: Config changes take effect immediately
```

### 4. Domain Separation

**Why It's Compatible:**
```
Mixed domains (OLD):
  call('light', 'turn_on', all_entities)
  Problem: Fails on switch.* entities

Separated (v3.2.0.8):
  lights = [e for e if e.startswith('light.')]
  switches = [e for e if e.startswith('switch.')]
  call('light', 'turn_on', lights)
  call('switch', 'turn_on', switches)
  Result: Works with Shelly and other multi-domain setups
```

### 5. Deferred Initialization

**Why It's Robust:**
```
Immediate initialization (OLD):
  Zone sensors created → Check for rooms → None found
  Problem: Race condition, sensors unavailable

Deferred (v3.2.9):
  Zone sensors created → Schedule retry
  After 5s → Check again → Rooms ready
  After 15s → Final check
  Result: Auto-recovery, no manual reload
```

---

## 🎯 VALUE PROPOSITIONS

### For Users

**Immediate Benefits:**
- Set it and forget it - automations just work
- Proper hysteresis - no device flickering
- Sleep protection - different rules at night
- Energy awareness - see consumption per room
- Visual feedback - alert lights for notifications
- Person tracking - know who is where

**Future Benefits (v3.3+):**
- Predictive comfort - pre-heat/cool before you arrive
- Light/music following - seamless room transitions
- Natural language customization - describe quirks in plain English
- Whole-house optimization - coordinated intelligence
- Visual mapping - see your home at a glance
- Bayesian predictions - learn your patterns

### For Smart Homes

**Current:**
- Coordinated behavior across rooms
- Zone-based intelligence
- Multi-person awareness
- Shared space management
- Safety monitoring with aggregation

**Future:**
- Cross-room coordination (v3.3)
- AI-powered customization (v3.4)
- Domain-level optimization (v3.6)
- Predictive intelligence (v4.0)
- Visual control center (v4.5)

### For Developers

**Why URA is Different:**
- Standard HA patterns (no hacks)
- Comprehensive test suite (178+ tests)
- Quality-first development
- Extensive documentation
- Clear architecture
- Extensible by design
- AI-powered flexibility (future)

---

## 📋 SUCCESS METRICS

### Technical (Achieved ✅)
- [x] Response time < 5 seconds (2-5s achieved)
- [x] Config changes immediate (v3.2.0.10)
- [x] Zero syntax errors in production
- [x] Backward compatibility maintained
- [x] Test coverage > 90%

### User Experience (In Progress)
- [x] "Livable automations" - no flickering
- [ ] Predictive accuracy > 80% (v4.0 target)
- [ ] Energy optimization > 15% (v3.6 target)
- [ ] Comfort scores > 80 average (v3.6 target)
- [x] Setup time < 30 minutes per room

### Quality (Achieved ✅)
- [x] Systematic validation before builds
- [x] Quality context read before coding
- [x] Test suite run before deployment
- [x] Documentation up to date
- [x] Regression prevention suite

---

## 🔮 FUTURE CONCEPTS (Backlog)

### Guest Mode
**Auto-detect and accommodate guests**
- Unknown Bluetooth device detected
- Frigate unknown face recognition
- Calendar shows "guest" event
- Behavior: Disable tracking, increase privacy, alert homeowner

### Vacation Mode Detection
**Auto-detect when traveling**
- No occupancy in any room for 24+ hours
- Phone GPS shows all phones away
- Calendar shows "vacation" events
- Behavior: Random lights, reduce HVAC, increase security

### Time Period Profiles
**Different behavior by time of day**
- Morning (6-9 AM): Gentle wake-up, gradual lights
- Daytime (9 AM-6 PM): Normal automation
- Evening (6-10 PM): Warmer lights, relaxed timeouts
- Night (10 PM-6 AM): Sleep protection active

### Weather Integration
**Weather-aware automation**
- Pre-cool before hot day
- Close blinds on sunny days
- Adjust HVAC based on forecast
- Energy optimization with solar forecast

---

## 🎓 LESSONS LEARNED

### What Works Well

**1. Event-Driven Architecture**
- Sub-5-second response times
- No polling delays
- Coordinator pattern scales well

**2. Tri-Level Entry System**
- Global config inheritance
- Zone-based grouping
- Room autonomy

**3. Test-First Development**
- 178+ tests prevent regressions
- Catch bugs before deployment
- Confidence in changes

**4. Quality Context System**
- Read before building prevents mistakes
- Documented patterns prevent repeats
- Cross-session consistency

**5. Config Storage Pattern**
- Merge entry.data + entry.options
- Changes take effect immediately
- User-friendly reconfiguration

### What to Avoid

**1. Coordinator Lifecycle Confusion**
- ❌ Don't use async_added_to_hass on coordinators
- ✅ Use async_config_entry_first_refresh instead

**2. Config Storage Mistakes**
- ❌ Don't only read entry.data
- ✅ Always merge entry.data + entry.options

**3. Domain Mixing**
- ❌ Don't call light.turn_on on switch entities
- ✅ Separate by domain before service calls

**4. Race Conditions**
- ❌ Don't assume resources ready immediately
- ✅ Use deferred initialization with retries

**5. Rushing Development**
- ❌ Don't skip quality context reading
- ✅ Systematic approach prevents cascades

---

## 🛣️ DEVELOPMENT ROADMAP SUMMARY

```
Timeline:     2026                           2027
              Q1    Q2    Q3    Q4    Q1    Q2
              │     │     │     │     │     │
v3.2.9 ━━━━━━┤     │     │     │     │     │  ← Current
v3.3.0 ───────┼─────┤     │     │     │     │  Cross-room
v3.4.0 ───────┼───────────┤     │     │     │  AI custom  ⭐
v3.6.0 ───────┼─────┼───────────┤     │     │  Coordinators
v4.0.0 ───────┼─────┼─────┼───────────┤     │  Bayesian  🧠
v4.5.0 ───────┼─────┼─────┼─────┼───────────┤  Visual    🗺️

Effort:       ~10h  ~15h  ~20h  ~5h   ~30h  ~40h
Priority:     MED   HIGH  MED   LOW   HIGH  MED
```

**Total Development:** ~120 hours over 18 months

---

## 📚 DOCUMENTATION ECOSYSTEM

### Core Documents
1. **VISION** (this doc) - Where we're going
2. **ROADMAP** - How we get there
3. **PLANNING** - What's next specifically
4. **QUALITY** - How we maintain excellence
5. **FRESH_SESSION** - How to onboard quickly

### Quality Documents
1. **DEVELOPMENT_CHECKLIST** - Pre-build validation
2. **CONFIG_FLOW_VALIDATION** - Storage pattern checks
3. **TEST_SUITE_ACCESS** - How to run tests
4. **COMPREHENSIVE_CONTEXT** - Complete system state

### Planning Documents
1. **v3_3_0_PLANNING** - Cross-room coordination spec
2. **v3_4_0_PLANNING** - AI customization spec
3. **Version READMEs** - Per-version release notes

---

## 🎉 CONCLUSION

Universal Room Automation has evolved from a simple room automation script to a sophisticated whole-house intelligence platform. We've achieved:

✅ Production-stable integration (v3.2.9)  
✅ Event-driven architecture (2-5s response)  
✅ Multi-person tracking framework  
✅ Zone-based coordination  
✅ Comprehensive test coverage (178+ tests)  
✅ Quality-first development process  

**Next Phase:** Cross-room coordination and AI-powered customization will transform URA from "smart rooms" to "intelligent home" - where the house understands your patterns, predicts your needs, and adapts to your quirks without code changes.

**The Vision:** A home that's not just automated, but truly intelligent. One that learns, predicts, coordinates, and optimizes - all while being "livable," respectful of manual overrides, and completely customizable through natural language.

**We're Building:** The future of residential automation - one room at a time, with quality and user experience as our north star.

---

**Vision Document v7.0**  
**Updated:** January 4, 2026  
**Next Update:** After v3.3.0 deployment  
**Status:** Active - guides all development decisions

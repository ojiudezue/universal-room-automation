# Universal Room Automation - Roadmap v9

**Version:** 9.0  
**Current Production:** v3.2.9  
**Current Development:** v3.3.x.x (bug fixes - music transitions, zone management)  
**Last Updated:** January 14, 2026  
**Status:** Active development - v3.3.x stabilization, then v3.5.0 camera intelligence  

---

## 🎯 EXECUTIVE SUMMARY

URA has evolved from blueprint-based room automation (v2.0) to a sophisticated whole-house intelligence system (v3.2.9). This roadmap charts the path from current production through camera-based intelligence, advanced predictive capabilities, and visual mapping.

**Current State:**
- Production: v3.2.9 (stable, tested)
- Development: v3.3.x.x (finalizing music transitions, bug fixes)
- Entities: 74+ per room
- Response: 2-5 seconds (event-driven)
- Tests: 178+ passing
- Architecture: Tri-level (Integration → Zones → Rooms)

**Next Major Milestone:**
- v3.5.0 - Camera Intelligence & Whole-House Census (Q2 2026)
- 15-18 hours effort
- Foundation for person-aware automation

**Note on v3.3.0/v3.4.0:**
- v3.3.0 (Cross-Room Coordination) - partially complete, being refined in v3.3.x.x patch series
- v3.4.0 (AI Custom Automation) - deferred until after v3.5.0 for architectural reasons
- v3.5.0 provides essential person tracking infrastructure that both features depend on

---

## 📊 VISUAL TIMELINE (UPDATED)

```
2026                                    2027
Q1        Q2        Q3        Q4        Q1        Q2
├─────────┼─────────┼─────────┼─────────┼─────────┤
│         │         │         │         │         │
v3.2.9    │         │         │         │         │
NOW       │         │         │         │         │
│         │         │         │         │         │
├─v3.3.x─┤│         │         │         │         │
  Bug Fix ││         │         │         │         │
  Music   ││         │         │         │         │
  (patches││         │         │         │         │
          ││         │         │         │         │
          ├┼v3.5.0──┤         │         │         │
           │ Camera │         │         │         │
           │ Intel  │         │         │         │
           │ Census │         │         │         │
           │(15-18h)│         │         │         │
                    │         │         │         │
                    ├─v3.4.0──┤         │         │
                      AI Cust │         │         │
                      (12-15h)│         │         │
                              │         │         │
                              ├─v3.6.0──┤         │
                                Domain  │         │
                                Coord   │         │
                                (15-20h)│         │
                                        │         │
                                        ├─────────┼─v4.0.0──┤
                                                  │ Bayesian│
                                                  │ Predict │
                                                  │ (20-30h)│
                                                            │
                                                            ├─v4.5.0
                                                              Visual
                                                              Mapping
                                                              (30-40h)
```

**Note:** v3.3.0 features (music following, transitions) are being refined in v3.3.x.x patch series before v3.5.0.

---

## ✅ COMPLETED MILESTONES

### Phase 1: Foundation (v2.0-2.3) - COMPLETE
**Timeline:** November 2025  
**Duration:** 2 weeks  

**Achievements:**
- 70+ entities per room
- Multi-sensor occupancy (PIR + mmWave + phone)
- Environmental monitoring
- Energy tracking
- SQLite database
- Basic automation engine

**Impact:** Established core architecture and patterns

---

### Phase 2: Reconfiguration (v2.4) - COMPLETE
**Timeline:** November 2025  
**Duration:** 1 week  

**Achievements:**
- Full options flow (8 config steps)
- Proper entry.options usage
- Backward compatibility
- Per-room reconfiguration

**Impact:** User-friendly configuration management

---

### Phase 3: Dual-Entry (v3.0) - COMPLETE
**Timeline:** November 2025  
**Duration:** 1 week  

**Achievements:**
- Integration entry (parent)
- Room entries (children)
- Notification inheritance
- Auto-migration from v2.4

**Impact:** Scalable multi-room architecture

---

### Phase 4: Aggregation & Zones (v3.1.0-3.1.5) - COMPLETE
**Timeline:** December 2025  
**Duration:** 2 weeks  

**Achievements:**
- Zone entry type (explicit)
- Whole-house aggregation
- Safety/security alerts
- Climate delta sensors
- Alert light support
- Water leak monitoring

**Impact:** Whole-house coordination foundation

---

### Phase 5: Enhanced Presence (v3.2.0-3.2.9) - COMPLETE
**Timeline:** December 2025 - January 2026  
**Duration:** 3 weeks  

**Achievements:**
- Bermuda BLE person tracking framework
- Multi-person support
- Room/zone/integration person sensors
- Database logging (visits, transitions)
- Confidence scoring
- Event-driven architecture (v3.2.0.9)
- Config storage pattern fix (v3.2.0.10)
- Real-time person updates (v3.2.8.3)
- Multi-domain device support (v3.2.8.2)
- Zone race condition fix (v3.2.9)
- Temperature fan switch support (v3.2.9)

**Test Coverage:** 178+ tests passing

**Critical Learnings:**
1. Coordinators ≠ Entities (different lifecycle)
2. Always merge entry.data + entry.options
3. Event listeners in async_config_entry_first_refresh
4. Domain separation for service calls
5. Deferred initialization for race conditions

**Status:** Stable in production

---

## 🚧 CURRENT WORK (v3.3.x.x)

### v3.3.x.x - Bug Fixes & Refinements 🔧
**Timeline:** January 2026  
**Duration:** Ongoing patches  
**Status:** IN PROGRESS  

**Focus Areas:**

**1. Music Transition Logic**
- WiiM media player handoff refinement
- Platform-agnostic music following
- Zone player entity fallback strategy
- Cross-room music coordination

**2. Zone Management**
- Zone sensor staleness issues
- Integration reload requirements
- Coordinator lifecycle improvements

**3. Person Tracking**
- Person sensor reliability
- BLE room-level precision
- Confidence scoring adjustments

**Test Coverage:** Maintaining 178+ passing tests

**Goal:** Stable v3.3.x foundation before v3.5.0 camera intelligence

---

## 🎯 ACTIVE ROADMAP

### v3.5.0 - Camera Intelligence & Whole-House Census 📹
**Timeline:** Q2 2026 (April-May)  
**Effort:** 15-18 hours  
**Priority:** VERY HIGH (foundational infrastructure)  
**Status:** Fully planned, ready to build after v3.3.x stabilizes  

**Theme:** "Person-aware whole-house intelligence"

**Why v3.5.0 Before v3.4.0?**
- Provides essential person tracking infrastructure
- v3.4.0 (AI Custom) and v3.6.0 (Domain Coordinators) both depend on census data
- Architectural foundation that unlocks multiple features
- Music following from v3.3.0 gets major upgrade with person identity

**Core Innovation:**
Integrates UniFi Protect + Frigate cameras with existing sensor fusion to create:
- **House Census System** - knows WHO is home, WHERE they are, HOW MANY guests
- **Dual Platform Redundancy** - UniFi + Frigate cross-validate for confidence boost
- **Transit Validation** - 2-4 hour camera heartbeat confirms BLE presence
- **Identity-Aware Automation** - personalized settings per person

**Key Features:**

**1. Camera Integration (Dual Platform)**
```python
# Cross-checking strategy, not division of labor
unifi_count = 3 persons
frigate_count = 3 persons

if both_agree:
    confidence = "very_high"  # 25% boost
    reliability = "excellent"
else:
    confidence = "medium"
    action = "investigate_disagreement"
```

**2. House Census System**
```yaml
sensor.ura_total_persons_home: 4
sensor.ura_identified_persons_home: "John, Jane"
sensor.ura_identified_count: 2
sensor.ura_unidentified_count: 2  # Guests
sensor.ura_census_confidence: "very_high"
```

**3. Enhanced Multi-Sensor Fusion**
```
Shared Spaces (Living Room) - SENSOR RICH:
├── Camera UniFi (0.85) - person detection
├── Camera Frigate (0.85) - cross-validation
├── BLE (0.70) - identity for known persons
├── mmWave (0.60) - occupancy confirmation
└── Motion (0.50) - supporting evidence
    └── Agreement Boost: cameras agree = 1.25x confidence
```

**4. Zone Person Aggregation**
```yaml
sensor.upstairs_person_count: 2
sensor.upstairs_identified_persons: "John, Jane"
sensor.downstairs_person_count: 2
sensor.downstairs_unidentified_count: 2  # Guests
```

**5. Transit Validation**
- BLE says "John in bedroom"
- Camera sees John in hallway → stairs → kitchen
- Conclusion: Phone left behind, person in kitchen
- Action: Follow music to actual location, not phone

**6. Security Anomalies**
```python
if census.unidentified_count > 0 and census.identified_count == 0:
    alert("Unknown person at home while everyone away")
    start_camera_recording()
```

**Sensor Architecture by Room Type:**

```
Private Rooms (Bedroom, Office):
├── BLE (identity + presence)
├── mmWave (occupancy)
├── Motion (supporting)
└── Cameras: NONE (privacy)

Shared Spaces (Living Room, Game Room):
├── Camera UniFi + Frigate (person count, cross-check)
├── BLE (identity)
├── mmWave (occupancy)
└── Motion (supporting)

Transition Zones (Hallways, Stairs):
├── Motion (primary - always present)
├── Camera (validation - where installed)
├── BLE (low weight - passing through)
└── mmWave (usually absent)
```

**Privacy-First Design:**
- Cameras ONLY in shared spaces + transition zones
- NO cameras in bedrooms/bathrooms/office
- Facial recognition opt-in only
- Guest privacy protection
- Privacy mode with auto schedule

**Platform Health Monitoring:**
```yaml
sensor.ura_camera_platform_health: "full"
  unifi_status: "online"
  frigate_status: "online"
  cross_validation_enabled: true
  agreement_rate_24h: 96.2%
  disagreements_today: 3
  reliability: "excellent"
```

**New Files:**
```
coordinators/
├── house_person_coordinator.py  (~400 lines)
camera/
├── integration_manager.py       (~250 lines)
├── dual_platform_manager.py     (~300 lines)
├── transit_validator.py         (~200 lines)
```

**Database:**
- house_census_snapshots (5-minute intervals)
- person_entry_exit_events
- transit_validation_events
- camera_person_events

**Success Criteria:**
- [x] Camera integration (UniFi + Frigate)
- [x] House census accurate (±1 person)
- [x] Transit validation working (4 hour timeout)
- [x] Zone person aggregation
- [x] Privacy modes functional
- [x] Security anomaly detection
- [x] Platform redundancy working
- [ ] 100+ new tests passing

**Integration with v3.3.0:**
- Music following gets person identity awareness
- Transition detection validated via camera checkpoints
- Pattern learning enhanced with identity data
- Cross-room intelligence uses census

**Enables v3.6.0:**
- Security Coordinator uses census for anomaly detection
- Energy Coordinator uses person count for HVAC load
- Comfort Coordinator uses person distribution
- HVAC Coordinator uses zone person counts

**Value:** 🌟 FOUNDATIONAL - Unlocks person-aware automation

**Priority Justification:**
- v3.4.0 (AI Custom) benefits from person-specific rules
- v3.6.0 (Domain Coordinators) requires census data
- v3.3.0 music following gets major upgrade
- Architectural dependency for future features

---

### v3.4.0 - AI Custom Automation 🤖
**Timeline:** Q3 2026 (After v3.5.0)  
**Effort:** 12-15 hours  
**Priority:** VERY HIGH (game-changer)  
**Status:** Planned - awaits v3.5.0  

**Theme:** "Natural language room customization"

**The Problem:**
EVERY room has quirks. Bed pressure sensor. TV on = don't turn off lights. CO₂ > 1000 = fan on. Complicated entity ID syntax. Jinja2 templates. Users can't code. Pain point #1.

**The Solution:**
```python
# User types in config UI:
"Use sensor.bed_pressure for occupancy. When it's over 50 lbs 
for 5 minutes, mark the room occupied. Don't turn off lights 
when the TV is on."

# Claude parses ONCE to structured rules (cached forever):
{
  "occupancy_override": {
    "entity_id": "sensor.bed_pressure",
    "condition": "above",
    "threshold": 50,
    "threshold_unit": "lbs",
    "duration_seconds": 300,
    "state_when_met": "occupied"
  },
  "light_control_conditions": [
    {
      "entity_id": "media_player.tv",
      "prevent_action": "turn_off",
      "when_state": "playing"
    }
  ]
}

# Runtime executes structured rules (ZERO AI cost)
```

**Key Innovation:**
- Parse ONCE at config time (uses AI, costs tokens)
- Cache structured rules FOREVER in entry.options
- Runtime executes rules (NO AI, NO cost, FAST)
- Manual re-parse only when user changes text

**Architecture:**
```python
Config Flow UI
    ↓ (User types natural language)
Claude API Parser
    ↓ (Parse to structured JSON rules)
Cache in entry.options
    ↓ (No AI cost from here on)
Runtime Engine
    ↓ (Execute rules, standard Home Assistant)
Room Automation
```

**Enhanced with v3.5.0 Census:**
```
"When John is in the room, set temperature to 68°F.
When Jane is in the room, set to 72°F.
When guests are present, use 70°F."

# v3.5.0 provides person identity:
if census.identified_persons == ["John"]:
    target_temp = 68
elif census.identified_persons == ["Jane"]:
    target_temp = 72
elif census.unidentified_count > 0:
    target_temp = 70  # Guests present
```

**Safety:**
- ✅ Structured rules (not arbitrary code)
- ✅ Sandboxed template engine
- ✅ Whitelisted operations only
- ✅ Graceful fallback if rules fail
- ✅ Standard automation always runs

**New Files:**
- custom_automation_parser.py: Claude API (~150 lines)
- custom_automation_engine.py: Rule execution (~200 lines)
- template_validator.py: Safe evaluation (~100 lines)

**Success Criteria:**
- [ ] Natural language parsed to structured rules
- [ ] Rules execute without runtime AI cost
- [ ] Person-specific rules (v3.5.0 census)
- [ ] Guest mode rules
- [ ] Safe sandboxed execution
- [ ] Config preview shows parsed rules

**Value:** 🌟 GAME-CHANGER - Ultimate flexibility without code

**Sequencing Note:** Now follows v3.5.0 to leverage person identity in custom rules.

---

### v3.6.0 - Domain Coordinators 🎯
**Timeline:** Q4 2026 (After v3.4.0)  
**Effort:** 15-20 hours  
**Priority:** HIGH  
**Status:** Planned - awaits v3.4-3.5  

**Theme:** "Whole-house intelligence layers"

**Enhanced with v3.5.0 Census:**

**1. Security Coordinator**
```python
# Uses census for anomaly detection
if census.unidentified_count > 0 and census.identified_count == 0:
    security_alert("Unknown person while everyone away")
    activate_cameras()

if census.total_persons > expected_occupancy + 3:
    security_alert("More people than expected")

# Person-specific security
if john_detected and security_mode == "away":
    security_mode = "home"  # Authorized person arrived
```

**2. Energy Coordinator**
```python
# Uses person count for HVAC load calculation
occupancy_load = census.total_persons
heat_load_adjustment = occupancy_load * 500  # BTU per person

# Leverage Oji's hardware:
# - 8x Encharge 5P batteries (40 kWh)
# - TOU rate awareness
# - SPAN panel circuit monitoring
# - Solcast solar forecasting

if battery_level < 20% and rate == "on_peak":
    # Load shed based on occupancy
    if census.total_persons == 0:
        shed_all_non_essential()
    else:
        shed_comfort_loads_only()  # People home, keep essentials
```

**3. Comfort Coordinator**
```python
# Uses person distribution for zone optimization
for zone in zones:
    if zone.person_count > 0:
        priority = "high"
        comfort_target = "normal"
    else:
        priority = "low"
        comfort_target = "eco"

# Identify bottleneck room with most people
worst_room = min(occupied_rooms, key=lambda r: r.comfort_score)
if worst_room.person_count > 2:
    priority_boost = True  # Multiple people suffering
```

**4. HVAC Coordinator**
```python
# Uses zone person counts for heat call priority
heat_calls = []
for zone in zones:
    if zone.needs_heating and zone.person_count > 0:
        priority = zone.person_count  # More people = higher priority
        heat_calls.append((zone, priority))

# Stagger based on occupancy
stagger_heat_calls(heat_calls, max_concurrent=3, priority_sort=True)
```

**New Files:**
```
coordinators/
├── security.py      (~250 lines, census integration)
├── energy.py        (~300 lines, person-aware load management)
├── comfort.py       (~250 lines, distribution optimization)
└── hvac.py          (~350 lines, occupancy-based priority)
```

**Success Criteria:**
- [ ] Security detects census anomalies
- [ ] Energy uses person count for HVAC load
- [ ] Comfort optimizes by person distribution
- [ ] HVAC priorities based on occupancy
- [ ] 15% energy reduction during peaks

**Value:** Whole-house optimization leveraging person intelligence

**Dependency Note:** Relies heavily on v3.5.0 census data for decision-making.

---

## 🌟 LONG-TERM VISION

### v4.0.0 - Bayesian Predictive Intelligence 🧠
**Timeline:** Q1 2027  
**Effort:** 20-30 hours  
**Priority:** VERY HIGH (capstone)  

**Philosophy:** Math-based probability, NOT neural networks

**Enhanced with v3.5.0 Person Identity:**

**Person-Specific Predictions:**
```python
# Instead of: "Someone will be in kitchen at 7 AM"
# Now: "John will be in kitchen at 7 AM (confidence: 0.85)"

P(John → Kitchen | 7AM, Weekday) = 0.85
P(Jane → Kitchen | 7AM, Weekday) = 0.45

# John almost always makes coffee
# Jane usually sleeps in
```

**Guest Pattern Detection:**
```python
# Learn guest behavior patterns
if census.unidentified_count > 0:
    guest_mode = True
    suppress_predictions = True  # Don't predict with guests

# After guests leave
update_baseline_patterns()  # Recalibrate without guest noise
```

**Confidence Boosting:**
```python
# v3.5.0 census provides validation
predicted_next_room = "kitchen"
camera_validates_movement = True
person_identity_matches = "John"

confidence = baseline_confidence * 1.3  # Identity + camera boost
```

**Why Bayesian:**
- ✅ Explainable predictions
- ✅ Uncertainty quantification
- ✅ Works with limited data
- ✅ Person-specific learning
- ✅ Guest-aware training

**Value:** 🌟 CAPSTONE - Predictive intelligence with person awareness

---

### v4.5.0 - Visual 2D Mapping 🗺️
**Timeline:** Q3 2027  
**Effort:** 30-40 hours  
**Priority:** MEDIUM  

**Enhanced with v3.5.0 Camera Data:**

**Real-Time Person Visualization:**
```
Floor Plan View:
┌─────────────────────────────────┐
│  Living Room                    │
│  ● John (camera detected)       │
│  ● Jane (camera detected)       │
│  ● Guest (unidentified)         │
│                                 │
│  Kitchen                        │
│  [empty]                        │
│                                 │
│  Bedroom                        │
│  📱 John's phone (BLE)          │
│  ⚠️  Person mismatch!           │
└─────────────────────────────────┘
```

**Camera Coverage Overlay:**
- Show camera field of view
- Highlight transition validation zones
- Display blind spots
- Census confidence heatmap

**Value:** Visual whole-house awareness with person tracking

---

## 📊 EFFORT vs VALUE MATRIX (UPDATED)

```
Value
High │
     │  v3.4 ●              v4.0 ●
     │  AI Custom            Bayesian
     │  (12-15h)             (20-30h)
     │
     │  v3.5 ●        v3.6 ●
     │  Camera        Domain
     │  Intel         Coord
     │  (15-18h)      (15-20h)
     │
     │         v3.3 ●
     │         Cross-
     │         Room
     │         (8-10h)
     │                              v4.5 ●
     │                              Visual
     │                              (30-40h)
Low  │
     └──────────────────────────────────────→ Effort
        Low                             High

● Size = Impact    Position = Priority
```

**Priority Ranking (UPDATED):**
1. **v3.5.0** - Camera Intelligence (FOUNDATIONAL - enables 3.4, 3.6, 4.0)
2. **v3.4.0** - AI Custom (VERY HIGH value, person-aware rules)
3. **v4.0.0** - Bayesian Predictions (VERY HIGH value, person-specific)
4. **v3.6.0** - Domain Coordinators (HIGH value, census-aware)
5. **v3.3.0** - Cross-Room (IN PROGRESS - v3.3.x.x patches)
6. **v4.5.0** - Visual Mapping (MEDIUM value, very high effort)

**Why v3.5.0 is Now Priority #1:**
- **Foundational Infrastructure** - v3.4, v3.6, and v4.0 all benefit from census
- **High Value Features** - Guest detection, security anomalies, person-aware automation
- **Architectural Dependency** - Unlocks person-specific everything
- **Reasonable Effort** - 15-18 hours, well-specified
- **No Blockers** - Can build immediately after v3.3.x.x stabilizes

---

## 🎯 KEY MILESTONES (UPDATED)

### Current (January 2026)
- [x] Event-driven architecture (v3.2.0.9)
- [x] Config storage fix (v3.2.0.10)
- [x] Real-time person tracking (v3.2.8.3)
- [x] Multi-domain devices (v3.2.8.2)
- [x] Zone race fix (v3.2.9)
- [ ] v3.3.x.x bug fixes (music transitions, zone management) - IN PROGRESS

### Near-Term (Next 6 Months)
- [ ] Camera intelligence (v3.5.0) - Q2 2026 (April-May)
- [ ] AI custom automation (v3.4.0) - Q3 2026 (After v3.5.0)

### Mid-Term (6-12 Months)
- [ ] Domain coordinators (v3.6.0) - Q4 2026
- [ ] Security intelligence (census-aware)
- [ ] Energy optimization (person count load)
- [ ] Comfort coordination (distribution-aware)
- [ ] HVAC management (occupancy priority)

### Long-Term (12+ Months)
- [ ] Bayesian predictions (v4.0.0) - Q1 2027
- [ ] Person-specific predictions
- [ ] Guest-aware learning
- [ ] Identity-validated confidence
- [ ] 2D visual mapping (v4.5.0) - Q3 2027
- [ ] Person tracking visualization

---

## 💡 STRATEGIC DECISIONS (UPDATED)

### Why v3.5.0 Now? (NEW)

**Foundational Infrastructure:**
- v3.4.0 AI Custom benefits from person-specific rules
- v3.6.0 Domain Coordinators requires census data
- v4.0.0 Bayesian needs person-specific patterns
- v3.3.0 music following gets identity awareness

**High Immediate Value:**
- Guest detection and auto guest-mode
- Security anomaly detection
- Phone left behind detection
- Whole-house occupancy state
- Person distribution optimization

**Architectural Unlock:**
- Enables person-aware everything
- Identity-based personalization
- Census confidence for all features
- Camera validation for predictions

**Well-Specified:**
- 15-18 hours effort (reasonable)
- Clear architecture (House Person Coordinator)
- Privacy-first design (no bedroom cameras)
- Dual platform redundancy (robust)
- Complete planning document ready

### Why Resequence from Original Roadmap?

**Original:** v3.3.0 → v3.4.0 → v3.6.0  
**Updated:** v3.3.x → v3.5.0 → v3.4.0 → v3.6.0  

**Rationale:**
1. **v3.3.0 started** but needs refinement (v3.3.x.x patches ongoing)
2. **v3.5.0 is foundational** for multiple downstream features
3. **v3.4.0 benefits** from person identity in custom rules
4. **v3.6.0 requires** census data for coordinators
5. **Dependency chain** v3.5 → v3.4 → v3.6 makes more sense architecturally

### Why v3.4.0 Still High Priority?

**Maximum Value:**
- ⭐ Solves THE biggest pain point (room customization)
- 🎯 Ultimate flexibility
- 🚀 No code changes needed
- 👤 Now with person-specific rules (v3.5.0 bonus)

**Reasonable Effort:**
- 12-15 hours (not 30+)
- Clear architecture
- Proven technology (Claude API)
- One-time AI cost

**Enhanced by v3.5.0:**
```
"When John is home, temperature 68. When Jane is home, 72.
When guests are present, 70."

# v3.5.0 census makes this possible!
```

---

## 🔄 BACKLOG IDEAS (UPDATED)

### Guest Mode (NOW ENABLED BY v3.5.0!)
- ✅ Auto-detect unknown persons (census)
- ✅ Disable location tracking
- ✅ Increase privacy
- ✅ Alert homeowner
- → Moves from backlog to v3.5.0 feature!

### Vacation Mode
- Auto-detect 24+ hours away (census confidence)
- Random light patterns
- Reduced HVAC
- Enhanced security

### Person-Specific Profiles (Enabled by v3.5.0)
- John's morning routine vs Jane's
- Per-person music preferences
- Individual comfort settings
- Custom automation per person

### Weather Integration
- Pre-cool before hot day
- Close blinds on sunny days
- Adjust HVAC with forecast
- Solar production optimization (Oji's Solcast)

---

## 📈 SUCCESS METRICS

### Technical (v3.2.9 ✅)
- [x] Response < 5 seconds (2-5s)
- [x] Config changes immediate
- [x] Test coverage > 90%
- [x] Zero syntax errors
- [x] Backward compatible

### User Experience (In Progress)
- [x] Livable automations
- [ ] Census accuracy > 95% (v3.5.0)
- [ ] Person tracking validated (v3.5.0)
- [ ] Guest detection working (v3.5.0)
- [ ] Predictions > 80% (v4.0)
- [ ] Energy optimize > 15% (v3.6)
- [ ] Comfort > 80 avg (v3.6)
- [x] Setup < 30 min/room

### Quality (Achieved ✅)
- [x] Systematic validation
- [x] Quality context read
- [x] Tests before deploy
- [x] Documentation current
- [x] Regression prevention

---

## 🎓 LESSONS LEARNED (UPDATED)

### What Works

**1. Event-Driven Architecture**
- 2-5 second response
- No polling overhead
- Scales well

**2. Quality-First Development**
- Read context before building
- Run tests before deploying
- Document all learnings
- Prevent regressions

**3. Test-Driven Development**
- 178+ tests
- Catch bugs early
- Confidence in changes
- Regression prevention

**4. Clear Architecture**
- Tri-level entry system
- Coordinator pattern
- Config storage pattern
- Domain separation

**5. Foundational Infrastructure First (NEW)**
- v3.5.0 camera intelligence enables multiple features
- Census data unlocks person-aware everything
- Architectural dependencies matter for sequencing

### What to Avoid

**1. Coordinator Confusion**
- async_added_to_hass doesn't run
- Use async_config_entry_first_refresh

**2. Config Storage Mistakes**
- Must merge data + options
- OptionsFlow updates options

**3. Domain Mixing**
- Separate before service calls
- light.turn_on fails on switches

**4. Race Conditions**
- Deferred initialization
- Retry logic with timeouts

**5. Rushing**
- Quality over speed
- Systematic prevents cascades
- Read context saves time

**6. Feature Sequencing (NEW)**
- Identify foundational infrastructure
- Build dependencies first
- Person tracking before person-aware features

---

## 🎉 CONCLUSION

URA has evolved from simple room automation to a sophisticated whole-house intelligence platform. We've achieved:

✅ Production stability (v3.2.9)  
✅ Event-driven response (2-5s)  
✅ Multi-person tracking framework  
✅ Zone coordination  
✅ Comprehensive testing (178+)  
✅ Quality process  
🚧 Music following refinement (v3.3.x.x)  

**Next Phase:** Camera intelligence (v3.5.0) provides the foundational infrastructure for person-aware automation across ALL future features.

**The Vision:** An intelligent home that learns, predicts, coordinates, and optimizes - all while being livable, respectful, privacy-conscious, and completely customizable through natural language. Now with precise person tracking and whole-house census intelligence.

**Timeline:** 18 months to v4.5.0, ~130 hours total effort (updated from 120)

**We're building the future of residential automation - one that knows WHO is home, not just that "someone" is there.**

---

**Roadmap v9.0**  
**Updated:** January 14, 2026  
**Changes from v8.0:**
- Added v3.5.0 Camera Intelligence (15-18h)
- Resequenced: v3.5.0 now before v3.4.0 (architectural dependencies)
- Enhanced v3.4.0, v3.6.0, v4.0.0 with person identity features
- Updated timeline and value matrix
- Added current state note (v3.3.x.x bug fixes)  
**Next Update:** After v3.5.0 deployment  
**Status:** Active development guide

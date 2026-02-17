# COORDINATOR DESIGN QUESTIONS SUMMARY

**Purpose:** Key design questions requiring your input before implementation  
**Total:** 24 questions across 8 coordinators

---

## PRESENCE COORDINATOR

**Document:** PRESENCE_COORDINATOR.md  
**Purpose:** House-level state inference (AWAY, HOME, SLEEP, etc.)

### Q1: Sleep Detection Method
How should sleep be detected?

**Options:**
1. Phone charging status (if phones charge in bedroom)
2. Smart mattress/sleep tracker integration
3. Light state + time (bedroom lights off after 10pm)
4. Explicit "goodnight" routine trigger
5. Motion absence + time

**Your Answer:** _______________________

### Q2: Guest Detection Policy
How conservative for GUEST mode?

**Options:**
1. **Conservative:** Any unknown person → GUEST mode immediately
2. **Moderate:** Unknown person + manual confirmation required
3. **Liberal:** Manual activation only (never auto-guest)

**Your Answer:** _______________________

### Q3: Geofence Integration
How to use geofence for ARRIVING state?

**Questions:**
- What radius triggers ARRIVING? (500m? 200m? 100m?)
- Pre-condition house on ARRIVING? (lights, HVAC)
- Trigger on first family member or wait for all?

**Your Answer:** _______________________

---

## SAFETY COORDINATOR

**Document:** SAFETY_COORDINATOR.md  
**Purpose:** Environmental hazard detection (smoke, CO, water, freeze)

### Q4: Water Shutoff Valve
Do you have or plan to add a smart water shutoff valve?

**Options:**
1. Yes, auto-shutoff on any leak detection
2. Yes, but require manual confirmation first
3. Yes, with auto-reopen policy after timeout
4. No smart valve currently

**Your Answer:** _______________________

### Q5: Smoke Detector Integration
What smoke detection approach?

**Options:**
1. Smart detectors with HA integration (Nest Protect, First Alert)
2. Interconnected dumb detectors + listener device
3. No HA smoke integration currently

**Your Answer:** _______________________

### Q6: Emergency Lighting Pattern
What should lights do on CRITICAL safety alert?

**Options:**
1. All lights 100% brightness
2. Affected area + egress path lights only
3. Flash pattern (orange for fire, blue for water)
4. Specific color (all red for fire warning)

**Your Answer:** _______________________

---

## SECURITY COORDINATOR

**Document:** SECURITY_COORDINATOR.md  
**Purpose:** Intrusion detection, access control, armed states

### Q7: Camera Integration Depth
How deep should camera integration go?

**Options:**
1. Person detection only (confirm entry events)
2. Person detection + auto-recording on events
3. Facial recognition (identify known vs unknown) - privacy implications
4. No camera integration

**Your Answer:** _______________________

### Q8: Smart Lock Integration
What smart lock behaviors?

**Options:**
1. Auto-lock doors when armed
2. Alert on unexpected unlock (during AWAY)
3. Temporary guest codes with expiration
4. All of the above
5. No smart lock integration

**Your Answer:** _______________________

### Q9: Geofence Radius for Security
At what distance should geofence signal "approaching"?

**Options:**
1. 500m (very early notification)
2. 200m (reasonable lead time)
3. 100m (just before arrival)

**Your Answer:** _______________________

---

## COMFORT COORDINATOR

**Document:** COMFORT_COORDINATOR.md  
**Purpose:** Room-level comfort (fans, lighting, temp preferences)

### Q10: Ceiling Fan Entity Pattern
What is your ceiling fan naming pattern?

**Examples:**
- `fan.{room}_ceiling_fan`
- `fan.{room}_fan`
- Bond integration specific patterns?

**Your Answer:** _______________________

### Q11: Room Temperature Sensors
What rooms have temperature sensors?

**Options:**
1. Provide mapping: `sensor.X_temperature` → room_id
2. Use area assignments in HA
3. Auto-discover by naming pattern

**Your Answer:** _______________________

### Q12: Circadian Light Selection
Which lights should follow circadian color temperature?

**Options:**
1. All smart bulbs with color temp capability
2. Only main room lights (not accent/task)
3. Explicit list of circadian-enabled lights
4. Specific rooms only (bedrooms, living areas)

**Your Answer:** _______________________

---

## ENERGY COORDINATOR

**Document:** ENERGY_COORDINATOR_DESIGN.md  
**Purpose:** Whole-house energy optimization, TOU management

### Q13: TOU Rate Schedule
What are your exact TOU rates and schedule?

**Needed:**
- On-peak hours and rate
- Off-peak hours and rate
- Shoulder periods (if any)
- Weekend schedule differences
- Utility provider name

**Your Answer:** _______________________

### Q14: Battery Strategy Priority
Primary goal for battery management?

**Options:**
1. Maximize self-consumption (minimize grid export)
2. Maximize bill savings (TOU arbitrage)
3. Maximize backup reserve (resilience)
4. Balanced approach

**Your Answer:** _______________________

### Q15: Controllable Loads
What high-power loads can be scheduled?

**Examples:**
- Pool pump (entity_id?)
- EV charger (entity_id?)
- Water heater (entity_id?)
- Dryer (smart plug?)

**Your Answer:** _______________________

---

## HVAC COORDINATOR

**Document:** HVAC_COORDINATOR_DESIGN.md  
**Purpose:** Zone-level HVAC control, Energy/Comfort integration

### Q16: Zone-to-Room Mapping
How do rooms map to your 3 Carrier Infinity zones?

**Format:**
```
Zone 1 (entity_id): [room1, room2, ...]
Zone 2 (entity_id): [room3, room4, ...]
Zone 3 (entity_id): [room5, room6, ...]
```

**Your Answer:** _______________________

### Q17: HVAC Pre-conditioning
How early should HVAC pre-condition on ARRIVING?

**Options:**
1. 30 minutes before expected arrival
2. 15 minutes before
3. On geofence trigger only
4. No pre-conditioning

**Your Answer:** _______________________

### Q18: Temperature Setback Limits
Maximum setback from comfort during constraints?

**Options:**
1. Conservative: ±2°F from preference
2. Moderate: ±4°F from preference
3. Aggressive: ±6°F from preference

**Your Answer:** _______________________

---

## NOTIFICATION MANAGER

**Document:** NOTIFICATION_MANAGER.md  
**Purpose:** Multi-channel notifications (iMessage, TTS, lights)

### Q19: iMessage Recipients
Who should receive notifications?

**Format:**
```
Primary: +1XXXXXXXXXX
Secondary: +1XXXXXXXXXX (optional)
```

**Your Answer:** _______________________

### Q20: TTS Speaker Entities
Which WiiM devices for voice announcements?

**Format:**
```
media_player.{x}
media_player.{y}
```

**Your Answer:** _______________________

### Q21: Light Alert Entities
Which lights for visual alert patterns?

**Options:**
1. All smart lights
2. Specific notification indicator lights
3. Entry/egress path lights only
4. Provide specific entity list

**Your Answer:** _______________________

---

## COORDINATOR ARCHITECTURE

**Document:** COORDINATOR_ARCHITECTURE.md  
**Purpose:** Overall coordinator interaction, conflict resolution

### Q22: Override Duration Default
How long should manual overrides last by default?

**Options:**
1. 1 hour (short duration)
2. 4 hours (half day)
3. Until next house state change
4. Until manually cleared

**Your Answer:** _______________________

### Q23: Diagnostic Logging Level
How verbose should coordinator logging be?

**Options:**
1. Minimal (errors only)
2. Standard (decisions + errors)
3. Verbose (all evaluations + decisions)
4. Debug (everything, for troubleshooting)

**Your Answer:** _______________________

### Q24: Conflict Resolution Philosophy
When coordinators conflict, what matters most?

**Ranking (1-4):**
- Safety: ___
- Energy efficiency: ___
- Comfort: ___
- Security: ___

**Current default:** Safety > Security > Energy > Comfort

**Your Answer:** _______________________

---

## QUICK REFERENCE - ALL QUESTIONS

| # | Coordinator | Topic | Short Description |
|---|-------------|-------|-------------------|
| 1 | Presence | Sleep Detection | How to detect sleep state |
| 2 | Presence | Guest Policy | Auto vs manual guest mode |
| 3 | Presence | Geofence | Radius and trigger policy |
| 4 | Safety | Water Valve | Auto-shutoff capability |
| 5 | Safety | Smoke Detectors | Integration type |
| 6 | Safety | Emergency Lights | Light behavior on alert |
| 7 | Security | Cameras | Integration depth |
| 8 | Security | Smart Locks | Lock automation policy |
| 9 | Security | Geofence | Security radius |
| 10 | Comfort | Fan Entities | Entity naming pattern |
| 11 | Comfort | Temp Sensors | Room mapping |
| 12 | Comfort | Circadian | Which lights included |
| 13 | Energy | TOU Rates | Your rate schedule |
| 14 | Energy | Battery | Primary optimization goal |
| 15 | Energy | Loads | Controllable high-power devices |
| 16 | HVAC | Zone Map | Rooms to zones |
| 17 | HVAC | Pre-condition | ARRIVING lead time |
| 18 | HVAC | Setback | Max temperature variance |
| 19 | Notify | iMessage | Recipient phone numbers |
| 20 | Notify | TTS | Speaker entity IDs |
| 21 | Notify | Lights | Alert light entities |
| 22 | Arch | Override | Default duration |
| 23 | Arch | Logging | Verbosity level |
| 24 | Arch | Priority | Coordinator ranking |

---

**Instructions:** Please answer the questions above. Answers can be brief - I'll follow up if I need clarification.

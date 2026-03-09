# PLAN: URA Dashboard v3 — Consumer-Grade Redesign

**Date:** 2026-03-04
**Scope:** Complete dashboard rebuild — 5 views, Mushroom-first, sections layout, auto-entities

---

## V2 Problems

1. **Home**: Sparse overview, people/location as separate cards, broken camera thumbnails
2. **Rooms**: Flat grid of binary_sensor chips showing "Clear"/"Detected" — no temp, no lights, no context
3. **Security**: Basic entity chips, grey camera grid, no visual urgency
4. **System**: Raw engineer dump of every coordinator sensor, automation health, config status — info overload

## V3 Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Glanceable** | Hero cards with gradient backgrounds for key status |
| **Room-first** | Rooms grouped by zone, each card shows occupancy + context |
| **Progressive disclosure** | Auto-entities show only occupied rooms, only non-normal health |
| **Color-coded** | Green=occupied/safe, amber=warning, red=alert, grey=vacant/off |
| **Consumer-grade** | Mushroom cards, sections layout, chip bars, no raw entity IDs visible |
| **Dynamic** | Auto-entities for rooms/health — no broken entity cards |

## Card Stack

| Card | Usage |
|------|-------|
| `mushroom-template-card` | Hero cards, room summary cards |
| `mushroom-chips-card` | Status chip bars |
| `mushroom-person-card` | People section |
| `mushroom-entity-card` | Individual entity display |
| `mushroom-climate-card` | HVAC zones |
| `auto-entities` | Dynamic room lists, health lists |
| `picture-entity` | Camera feeds |
| `card-mod` | Subtle gradient backgrounds |
| `stack-in-card` | Grouped cards without borders |

## V3 Views

### View 1: Home Overview
- **Hero**: House state with gradient, rooms occupied, people home
- **Chips**: Weather, safety status, security armed, music following
- **People**: 4 person cards (mushroom-person-card auto-merges location)
- **Occupied Rooms**: Auto-entities showing only currently occupied rooms
- **Camera Peek**: 4 key entry/perimeter cameras

### View 2: Rooms
- **Main Living**: Kitchen, Breakfast Nook, Dining, Living, Receiving
- **Bedrooms & Studies**: Master, Study A, Study B, Game Room
- **Guest & Kids**: Guest 1, Guest 2, Ziri, Guest Baths
- **Utility**: AV Closet, Stair Closet, Laundry, Media Closet, Garage, Patio
- Each room: mushroom-template-card with icon, occupancy color, state text

### View 3: Security
- **Hero**: Armed state + alert indicator
- **Access Control**: Front door lock, Garage A, Garage B, Alarm panel
- **Perimeter Cameras**: 8 cameras (front, sides, rear, pool area)
- **Entry Cameras**: Entry, doorbell, garages
- **Interior Cameras**: Foyer, stairs, halls, playroom, family room

### View 4: Safety & Notifications
- **Safety Hero**: Status + active hazards count
- **Hazard Indicators**: Water leak, air quality, safety alert binary sensors
- **Notification Manager**: Last notification, today count, channel status, delivery rate
- **Coordinator Diagnostics**: Anomaly + compliance for all coordinators

### View 5: System (Admin)
- **Coordinator Controls**: Master toggle + per-coordinator enable switches
- **Coordinator Health**: Manager status, house state, summary
- **Climate**: HVAC zones with climate cards
- **Automation Health**: Auto-entities showing only non-normal rooms
- **Config Status**: Auto-entities showing only non-OK rooms

## Entity IDs Used

### Coordinator Sensors
- `sensor.ura_coordinator_manager_house_state` (home_day)
- `sensor.ura_coordinator_manager_coordinator_summary` (all_clear)
- `sensor.ura_presence_coordinator_*` (house_state, confidence, anomaly, compliance)
- `sensor.ura_safety_coordinator_*` (status, hazards, rooms, diagnostics, anomaly, compliance)
- `sensor.ura_security_coordinator_*` (armed_state, last_entry, anomaly, compliance)
- `sensor.ura_music_following_coordinator_*` (anomaly, transfers, active_rooms, health)
- `sensor.ura_notification_manager_*` (last, today, cooldown, channels, trigger, anomaly, delivery, diagnostics)

### Binary Sensors
- `binary_sensor.ura_presence_coordinator_house_occupied`
- `binary_sensor.ura_safety_coordinator_safety_alert`
- `binary_sensor.ura_safety_coordinator_safety_water_leak`
- `binary_sensor.ura_security_coordinator_security_alert`
- `binary_sensor.ura_notification_manager_notification_active_alert`
- `binary_sensor.*_occupied` (23 rooms)

### Switches
- `switch.universal_room_automation_domain_coordinators_enabled`
- `switch.ura_presence_coordinator_enabled`
- `switch.ura_safety_coordinator_enabled`
- `switch.ura_security_coordinator_enabled`
- `switch.ura_music_following_enabled`
- `switch.ura_notification_manager_enabled`

### People, Weather, Security
- `person.oji_udezue`, `person.ezinne`, `person.jaya`, `person.ziri`
- `weather.phalanxmadrone`
- `alarm_control_panel.elkm1_area_1`
- `lock.doorlock_kwikset_zwave_frontentry`
- `cover.konnected_f0f5bd523b00_garage_door` / `cover.ratgdov25i_dbfe2a_door`

### Climate
- `climate.thermostat_bryant_wifi_studyb_zone_1` (Zone 1)
- `climate.up_hallway_zone_2` (Zone 2)
- `climate.back_hallway_zone_3` (Zone 3)
- `climate.master_suite_zone_1` (Master)

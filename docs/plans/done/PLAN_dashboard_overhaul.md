# Plan: URA Diagnostics Dashboard Overhaul (v3.6.22)

**Date:** 2026-03-02
**Status:** Planned (not yet implemented)

## Context

The URA Diagnostics dashboard was built pre-coordinators (v3.5.0). It uses plain tile/entities cards across 6 views. Major gaps: 13 of 23 rooms missing, no coordinator content, no zone monitoring, no music following, "unknown" entities polluting System Health tab.

**Installed card toolkit:** Mushroom v5.1.1, card-mod v4.2.1, button-card v7.0.1, Bubble Card v3.1.1, Prism v1.8.6, auto-entities, mini-graph-card, apexcharts-card, layout-card, area-card-plus, Material You theme. All needed tools are present.

## Dashboard Architecture — 7 Views

### View 1: Overview (`overview`)
- **House State hero** — Mushroom template card with dynamic icon/color per state (sleep/away/home_day/home_evening/arriving)
- **Quick Stats** — Mushroom chips: rooms occupied, people home, tracking status
- **Alerts section** — Conditional cards: only show when active (safety, security, unexpected person, perimeter)
- **Where Is Everyone** — Mushroom person cards for 4 family members
- **Room Occupancy Grid** — ALL 23 rooms as compact Mushroom entity cards (green=occupied)
- **Music Following** — Health sensor card

### View 2: Coordinators (`coordinators`) — NEW
- **Coordinator Toggles** — Master + 3 coordinator switches
- **Presence** — House state, confidence, anomaly, compliance, occupied, sleeping, guest mode
- **Safety** — Status, active hazards, affected rooms, diagnostics, anomaly, compliance, water leak, air quality
- **Security** — Armed state, last entry, anomaly, compliance, alert
- **Music Following** — Health sensor with attributes

### View 3: Zones (`zones`) — NEW
- One section per zone: Back Hallway, Entertainment, Master Suite, Outside, Upstairs
- Each: rooms occupied, active rooms, avg temp/humidity, occupant count, presence status
- Mini-graph-card for temperature trends

### View 4: Room Detail (`rooms`)
ALL 23 rooms (was 10). Each room section:
- Mushroom entity card: occupied (color-coded)
- Mushroom chips: people count, temperature, humidity
- Entities: identified people, timeout, automation health
- Automation: last trigger/action/time
- History graph: 12h occupancy

### View 5: People (`people`)
Upgrade to Mushroom person cards, keep movement path + predicted next room + history graphs.

### View 6: Automation (`automation`)
- ALL room automation switches (was 9, now 23)
- Automation health grid — ALL 23 rooms' `sensor.*_automation_health`
- Recent trigger/action log

### View 7: System Health (`system`)
- **Remove "unknown" entities**: whole_house_power, whole_house_energy_today, predicted cooling/heating, outdoor temp/humidity deltas
- **Add coordinator summary**: manager status, coordinator summary, house state override
- **Configuration status** — ALL rooms (was 5)
- **Unavailable entities** — ALL rooms (was 5)
- Keep integration update tile

## Mushroom Card Patterns

### House State Hero
```yaml
type: custom:mushroom-template-card
primary: House State
secondary: "{{ states('sensor.ura_coordinator_manager_house_state') | replace('_', ' ') | title }}"
icon: >-
  {% set s = states('sensor.ura_coordinator_manager_house_state') %}
  {% if s == 'sleep' %}mdi:sleep
  {% elif s == 'away' %}mdi:home-export-outline
  {% elif s == 'home_day' %}mdi:white-balance-sunny
  {% elif s == 'home_evening' %}mdi:weather-night
  {% else %}mdi:home{% endif %}
icon_color: >-
  {% set s = states('sensor.ura_coordinator_manager_house_state') %}
  {% if s == 'sleep' %}deep-purple
  {% elif s == 'away' %}grey
  {% elif s == 'home_day' %}amber
  {% elif s == 'home_evening' %}indigo
  {% else %}blue{% endif %}
layout: horizontal
```

### Compact Room Chip
```yaml
type: custom:mushroom-entity-card
entity: binary_sensor.kitchen_occupied
name: Kitchen
layout: horizontal
```

### Conditional Alert
```yaml
type: conditional
conditions:
  - condition: state
    entity: binary_sensor.universal_room_automation_safety_alert
    state: "on"
card:
  type: custom:mushroom-entity-card
  entity: binary_sensor.universal_room_automation_safety_alert
  icon_color: red
```

## All 23 Rooms — Entity Prefixes

| Room | Prefix | Sensors |
|------|--------|---------|
| Kitchen | `kitchen_` | Full |
| Kitchen Hallway | `kitchen_hallway_` | Full |
| Breakfast Nook | `breakfast_nook_` | Partial |
| Dining Room | `dining_room_` | Partial |
| Living Room | `living_room_` | Full |
| Receiving Room | `receiving_room_` | Partial |
| Master Bedroom | `master_bedroom_` | Partial |
| Study A | `studya_room_device_` | Partial |
| Study B | `study_b_` | Partial |
| Study A Closet | `study_a_closet_` | Minimal |
| Game Room | `game_room_` | Partial |
| Guest Bedroom 1 | `guest_bedroom_1_` | Partial |
| Guest Bedroom 2 | `upstairs_guest_bedroom_` | Partial |
| Guest Bed 2 Bath | `guest_bedroom_2_bathroom_` | Partial |
| Down Guest Bath | `down_guest_bathroom_` | Partial |
| Ziri Bedroom | `ziri_bedroom_bedroom_5_` | Partial |
| Patio | `patio_` | Minimal |
| Garage A | `garage_a_` | Partial |
| AV Closet | `av_closet_` | Minimal |
| Stair Closet | `stair_closet_` | Minimal |
| Media Room Closet | `media_room_closet_` | Minimal |
| Laundry Closet | `laundry_closet_` | Minimal |
| Exercise Room Closet | `exercise_room_closet_` | Minimal |

## 5 Zones

| Zone | Prefix |
|------|--------|
| Back Hallway | `zone_back_hallway_` |
| Entertainment | `zone_entertainment_` |
| Master Suite | `zone_master_suite_` |
| Outside | `zone_outside_` |
| Upstairs | `zone_upstairs_` |

## Coordinator Entities (confirmed active)

### Presence
`sensor.ura_presence_coordinator_presence_house_state` (home_day), `*_house_state_confidence` (0.85), `*_presence_anomaly` (learning), `*_presence_compliance` (100%), `binary_sensor.*_house_occupied` (on), `*_house_sleeping` (off), `*_guest_mode` (off), `switch.ura_presence_coordinator_enabled` (on)

### Safety
`sensor.ura_safety_coordinator_safety_status` (normal), `*_safety_active_hazards` (0), `*_safety_affected_rooms` (clear), `*_safety_diagnostics` (degraded), `*_safety_anomaly` (disabled), `*_safety_compliance` (100%), `binary_sensor.*_safety_alert` (off), `*_safety_water_leak` (off), `*_safety_air_quality` (off), `switch.ura_safety_coordinator_enabled` (off)

### Security
`sensor.ura_security_coordinator_security_armed_state` (disarmed), `*_security_last_entry` (none), `*_security_anomaly` (learning), `*_security_compliance` (0%), `binary_sensor.*_security_alert` (off), `switch.ura_security_coordinator_enabled` (on)

### Manager
`sensor.ura_coordinator_manager_coordinator_manager` (running), `*_house_state` (home_day), `*_coordinator_summary` (all_clear), `switch.universal_room_automation_domain_coordinators` (on)

## Implementation

### Step 1: Build full dashboard config as JSON object
Construct all 7 views with Mushroom cards, covering all 23 rooms, all coordinators, all 5 zones.

### Step 2: Deploy via MCP
`mcp__home-assistant-remote__ha_config_set_dashboard(url_path="ura-diagnostics", config=full_config)`

### Step 3: Verify
All 7 tabs load, all rooms present, coordinator data visible, no unknown entities, Mushroom cards render correctly.

## Deferred

- **Config UX P0-1 (area pre-population)** — separate cycle, requires config_flow.py changes
- **Glassmorphism/Prism styling** — can be layered on after functional overhaul via card-mod
- **Bubble Card pop-ups** — enhancement after base dashboard works

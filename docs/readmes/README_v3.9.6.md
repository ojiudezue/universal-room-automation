# URA v3.9.6 — Dashboard v2 Round 2 + HA 2026.3 Compliance

## Dashboard v2 Round 2
Rebuilt all four primary tabs with card-based layouts replacing flat entity lists:

- **RoomsTab**: Room-centric data model grouping lights/climate/motion by room name matching. Expandable room cards with health dots, motion indicators, light toggle buttons with brightness, and climate displays with large temperature readout. Floor plan tabs for ground/second floor.

- **SecurityTab**: Alarm panel with 4-button control grid (Home/Away/Night/Disarm) with confirmation flow. Lock cards with colored borders (green=locked, red=unlocked) and confirmation-required unlock. Camera thumbnails from entity_picture with recording indicator animation. Summary stat cards for locks/entries/arrivals.

- **DiagnosticsTab**: Coordinator cards with toggle switches and colored accent icons. Automation health shown as compact tile grid with progress bar summary. Anomaly cards with alert highlighting. System info in 2x2 grid.

- **PresenceTab**: Person cards with avatar images, tracking source, and transition history. Four detection layer cards in 2x2 grid: Motion Sensors, BLE Tracking, Camera Activity, Zone Occupancy. Music following grid.

### Review fixes applied:
- `timeAgo()` NaN guard for invalid dates
- `healthColor` consistency between RoomsTab and DiagnosticsTab (poor → orange, very_poor → red)

## HA 2026.3 Breaking Changes Compliance

### URA Integration Code
- `automation.py:534` — `service_data["kelvin"]` → `service_data["color_temp_kelvin"]`
- `automation.py:1323/1350` — Alert light restore: `color_temp` attribute/service key → `color_temp_kelvin`

### HA Automations Fixed (8 running)
| Automation | Old (mireds) | New (Kelvin) |
|---|---|---|
| master_closet_storage_smart_lighting_v2 | 300, 350 | 3333K, 2857K |
| livingroom_hallway_automation | 250 | 4000K |
| smart_staircase_night_light | 250 | 4000K |
| ziri_bathroom_night_light | 320 | 3125K |
| jaya_night_light_automation | 320 | 3125K |
| guest_bathroom_night_light | 320 | 3125K |
| stair_closet_night_light_automation | 250 | 4000K |
| guest_toilet_automation2 | 400, 320 | 2500K, 3125K |

### Dependencies
- Added `lucide-react` for tree-shakeable icons

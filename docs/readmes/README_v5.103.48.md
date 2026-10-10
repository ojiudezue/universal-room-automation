# URA v5.103.48 — Room switches found by registry, not by name

Tier 2: build, two reviews (A correctness/test authority — FIX-REQUIRED then fixed; B lifecycle/live impact — SHIP), orchestrator re-drill, full-suite name-diff 0 new. Card: ROOM-SWITCH-LOOKUP-BY-NAME-1.

## Problem
URA found each room's control switches (Automation, AI Automation, Manual mode, Cover automation, Override occupied/vacant, Device auto recovery) by building a name from the room name: `switch.<room>_<switch>`. Home Assistant names new entities `switch.<device>_<entity>`, which often doubles the room name (`switch.chinenye_room_chinenye_room_automation`) or differs entirely (`switch.ziri_bedroom_bedroom_5_*`, and rooms with brackets in their name can never match). When the built name didn't exist, URA assumed the switch was ON — so turning a room off did nothing. Found at Wigton (all 19 rooms) and in 34 main-house rooms; 8 main-house rooms had OFF switches being ignored.

## Fix
- Each room switch is resolved through the entity registry by its unique_id (`<entry_id>_<switch>`), so any entity id works — original, doubled, or renamed by the operator. The built name is only a fallback.
- A switch that can't be found logs one warning (after a second consecutive miss, so a brand-new room's first refresh doesn't false-alarm) instead of failing silently.
- Override occupied/vacant mutual exclusion uses the same resolver.

## Live impact
- Rooms whose switches are OFF now actually stop: Foyer, Guest Bedroom 2, Jaya Bedroom, Master Closet, Master Hallway, Media (Automation), Master Toilet (AI), Ziri Bedroom (the only one not already fixed by the 2026-10-10 manual renames). Operator approved.
- No override is ON anywhere, so no room is suddenly forced occupied/vacant.

## Live validation (prospective)
- Ziri Bedroom: Automation switch OFF ⇒ no URA light action on occupancy change.
- No "room switch not found" warnings after boot for existing rooms.
- No URA errors at boot.

## Validated 2026-10-10 (HA restarted 2026-10-10 15:52 UTC)

| Acceptance criterion | Result | Evidence |
|---|---|---|
| No "room switch not found" / resolver warnings since restart | PASS | `ha_get_logs(source=system_service, slug=core, search="room switch not found", hours_back=4)` → 0 lines; `search="resolver"` → 0 lines; `search="universal_room_automation"` → 0 lines (confirms no URA log activity at all, not just no matches on this phrase) |
| No URA errors since restart | PASS | Same `search="universal_room_automation"` pull → 0 lines in system_service core log |
| 7 Automation-OFF rooms (Foyer, Guest Bedroom 2, Jaya Bedroom, Master Closet, Master Hallway, Media, Ziri Bedroom): occupancy changed but no URA light/switch action | PASS | `ura_activity_log` for these 7 room names since `2026-10-10T15:52:00` with `action LIKE '%light%' OR '%switch%' OR '%turn%'` → **0 rows**. Occupancy DID flip for 3 of the 7 in that window (confirms the gate was actually exercised, not just quiet): Jaya Bedroom presence on/off 12:56:59→13:49:47 CDT; Master Closet occupancy on/off ×2 ~13:10–13:12 CDT; Master Hallway occupancy on/off ×10 ~12:26–13:12 CDT (`ha_get_history`, `binary_sensor.jaya_3_presence`, `binary_sensor.rgbw_lux_motion_3rdr_wifi_mastercloset_occupancy`, `binary_sensor.rgbw_motion_lux_3rd_zigbee_masterhallway_occupancy` + `..._masterhallway_presence`). Guest Bedroom 2, Media, Ziri Bedroom stayed `off` (no edges) in the window; Foyer has no configured sensors at all (`.storage/core.config_entries` — `motion_sensors`/`occupancy_sensors`/`lights` all unset for that entry) so nothing to exercise. |
| Ziri Bedroom: Automation OFF ⇒ no URA light action on occupancy change | PASS (by absence — room had no occupancy edge in-window) | Config entry title is `Ziri Bedroom (Bedroom 5)`, entry_id `01KJJN92CZ4KEM6WXB3168N8YW`; `lights`/`night_lights`/`motion_sensors`/`presence_sensors` are all `None`/`[]` in current config (no lights currently assigned to the room at all), and `binary_sensor.ziri_3_presence`/`ziri_3_moving_target`/`mmwave_zigbee_ziribedroom_presence` show no `on` transitions since restart — so the specific entry/exit-light scenario in the criterion did not occur live this window; the row above (no light/switch rows at all for the 7 rooms) is the operative evidence. |
| Master Toilet: AI automation off ⇒ no AI-chain actions | Not directly observable this window | `ura_activity_log` shows normal light/switch entry/exit cycling for Master Bath Toilet (the only room-name match) through the window — e.g. `light_turn_on`/`light_reconcile`/`light_turn_off` at 17:18–18:54 UTC — consistent with base automation (Automation switch ON) continuing to run while only AI-chain actions are suppressed; no AI-chain action log entries (`action LIKE '%ai_%'`) were produced to confirm the negative either way, since no AI-triggerable condition arose in this window. |

Note: resolved the room-name ambiguity the task brief used — the actual config-entry titles are `Ziri Bedroom (Bedroom 5)`, `Jaya Bedroom (Bedroom 4)`, and `Master Bath Toilet` (not `Master Toilet`); queries above used the real titles.

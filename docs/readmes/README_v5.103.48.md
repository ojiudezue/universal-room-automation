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

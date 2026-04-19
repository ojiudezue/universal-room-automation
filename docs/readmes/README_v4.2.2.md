# v4.2.2 — HVAC Zone Entry Dwell

**Date:** April 19, 2026
**Scope:** HVAC zone preset flapping prevention
**Tests:** 1478 passing (no regressions)

## Problem

When someone briefly walks through a zone (e.g., back hallway to get to the
garage), the zone switches from "away" to "home" preset. The existing 15-minute
vacancy grace period then keeps the zone on "home" for ~20 minutes before it
reverts to "away". This wastes HVAC energy conditioning a zone nobody is using.

## Solution

A configurable **zone entry dwell** — the zone must be continuously occupied for
N minutes before the HVAC preset changes from "away" to "home". If the person
leaves before the dwell expires, the zone never changed preset. Default: 3 minutes.

3-5 minutes of slightly delayed comfort saves 20 minutes of wasted HVAC energy.

## How It Works

### The Dwell Decision

When the HVAC coordinator evaluates zone presets (every 5 minutes), for each zone:

```
IF house is already occupied (home_day/evening/night, guest, waking)
  AND zone just became occupied
  AND zone has been occupied for LESS than dwell_minutes
  AND zone is NOT a pre-arrival zone
  AND the target preset is NOT "away" (vacancy override still works)
THEN: skip preset change — keep whatever preset the zone currently has
```

On the next decision cycle, if the person is still there, the dwell will have
been met and the preset changes normally. If they left, the zone never flapped.

### What It Does NOT Affect

**Pre-arrival conditioning:** Zones in the `_pre_arrival_zones` set are explicitly
excluded from dwell. When a geofence/BLE signal fires, pre-arrival applies a
-2F offset to the arriving person's preferred zones immediately — no dwell delay.
This means pre-arrival provides comfort during the dwell period if someone is
genuinely arriving home.

**Away/arriving house states:** The dwell only applies when the house is already
occupied. When the house state is "away" or "arriving", no dwell — the existing
"arriving" state hold (30-60s) and pre-arrival conditioning handle that transition.

**Vacancy override (D1):** If a zone has been vacant past the grace period and the
effective preset is "away", the dwell does NOT block that. The `effective_preset != "away"`
guard ensures vacancy overrides still fire immediately.

**Sleep preset:** Sleep preset changes are not affected because the house state
is "sleep", not one of the occupied states the dwell checks for.

**Pre-cooling:** Weather-driven pre-cooling operates on occupied zones only and
applies offsets directly — it doesn't go through the preset change path that
the dwell guards. No conflict.

### Interaction With Existing Dwell Layers

URA already has multi-layer occupancy debouncing. Zone entry dwell adds one more:

| Layer | Duration | What it prevents |
|-------|----------|-----------------|
| Room motion debounce | 150ms | Sub-150ms sensor flutter |
| Room occupancy timeout | 5 min (configurable per room type) | Room stays "occupied" after last motion |
| **Zone entry dwell (NEW)** | **3 min (configurable)** | **Zone preset change on brief transit** |
| Zone vacancy grace (D1) | 15 min (5 min constrained) | Zone stays on "home" after going vacant |
| HVAC decision cycle | 5 min polling | Natural batching of preset changes |

### Timing Example: Brief Transit

1. Person walks through back hallway (10 seconds of motion)
2. Room detects motion → occupied (after 150ms debounce)
3. Zone `current_session_start` set to now
4. Person leaves → room stays occupied for 5 min (timeout)
5. HVAC cycle fires → zone occupied for <3 min → **dwell blocks preset change**
6. Room occupancy expires at 5 min → zone vacant → `current_session_start` reset
7. Zone never changed to "home" preset — **no energy wasted**

### Timing Example: Genuine Occupancy

1. Person enters zone and stays (settles into room)
2. Room detects motion → occupied
3. Zone `current_session_start` set to now
4. First HVAC cycle: occupied for <3 min → dwell blocks (keeps "away")
5. Second HVAC cycle (5 min later): occupied for >3 min → **dwell met, "home" preset applied**
6. 3-5 minute delay to comfort — acceptable tradeoff

## Configuration

### Config Flow
Settings > Devices > URA: Coordinator Manager > Configure > HVAC
- **Zone Entry Dwell** — Slider, 0-15 minutes, default 3
- Set to 0 to disable dwell entirely

### Number Entity (Runtime)
`number.ura_hvac_coordinator_zone_entry_dwell` on the HVAC Coordinator device card.
Adjustable at runtime without reconfiguration — takes effect on next HVAC decision cycle.

## Files Changed
- `hvac_const.py` — `CONF_HVAC_ZONE_ENTRY_DWELL`, `DEFAULT_ZONE_ENTRY_DWELL_MINUTES`
- `hvac_zones.py` — `current_session_start` field + tracking in zone condition update
- `hvac.py` — Dwell check in `_apply_house_state_presets()`, new `__init__` param
- `number.py` — `ZoneEntryDwellNumber` entity on HVAC Coordinator device + CM entry path
- `config_flow.py` — Slider in `async_step_coordinator_hvac`
- `strings.json` / `translations/en.json` — Labels + descriptions

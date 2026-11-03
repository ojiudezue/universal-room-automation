# Shared-space auto-off as a vacancy-gated failsafe

Card: SHARED-SPACE-AUTO-OFF-FAILSAFE-1. Tier 2 (lighting behaviour in the 30 rooms that have `shared_space` set; no DB change, no zone-sweep change).

## Problem
- 2026-11-02/03: `light.dimmer_tapo_wifi_matter_kitchenoverhead` stayed on from 21:16 to 05:01.
- The Kitchen has `lights_leave_on_when_empty = [overhead]`.
- `_shared_space_turn_off_all` exempts leave-on lights (`automation.py:4681`), so the 23:00 sweep skipped the overhead.
- `check_scheduled_auto_off` (`automation.py:4464`) only fires during hour == auto_off_hour, and it ignores occupancy.

## Operator decisions (2026-11-03)
- This sweep is the night failsafe. It ignores the leave-on list.
- It runs only when the room is vacant. Room occupancy already excludes stuck sensors (`coordinator.py:2908`).
- From the auto-off hour onwards, it retries every tick until the first vacant tick. It gives up at a cutoff hour (default 05:00).
- Accepted trade: a false "occupied" means no sweep that night.
- The manual-on hold (`light_hold_allowed`) stays.
- The T-5 warning flash fires only when the room is occupied.

## Falsifiable invariant
For a shared-space room, if any tick between the auto-off hour and the cutoff sees the room vacant, then every light, night light and leave-on light not held by `light_hold_allowed` is turned off exactly once that night. No sweep fires on an occupied tick, or outside the window.

## Deliverables
**D1. Window plus vacancy gate**
- `check_scheduled_auto_off` is eligible when the local time is inside the window [auto_off_hour, cutoff). The window may wrap midnight; 23 → 5 is the normal case.
- It also requires that the room is vacant and that the sweep has not already fired for this night.
- "Night" is keyed by the date on which the window opened. Use the date the window started, not the calendar date, so the sweep can't fire twice across midnight.
- Prior art: read how the coordinator exposes room occupancy before choosing the vacancy source. REUSE that source; do not re-derive it.

**D2. Leave-on included in this sweep only**
- `_shared_space_turn_off_all` stops excluding `lights_leave_on_when_empty`.
- The vacancy exit path and the zone sweep keep honouring leave-on.
- Check every caller of `_shared_space_turn_off_all` first. If anything other than the scheduled auto-off calls it, use a parameter rather than a global change.

**D3. Cutoff knob**
- `CONF_SHARED_SPACE_AUTO_OFF_CUTOFF_HOUR`, default 5, at rung 2 (options flow, next to `CONF_SHARED_SPACE_AUTO_OFF_HOUR`).
- If cutoff == auto-off hour, the window is that one hour only, which is today's behaviour. Document this on the knob.
- grep `const.py` and `config_flow.py` first to make sure no equivalent exists.

**D4. Flash only when occupied**
- `check_auto_off_warning` adds an occupied condition.

## Non-goals
Zone sweep, vacancy exit path, fans' sweep semantics beyond what `_shared_space_turn_off_all` already does, any change to stuck detection.

## Acceptance criteria
- **Test:** an occupied tick at 23:00 gives no sweep. The first vacant tick at 01:30 sweeps, including leave-on. A later vacant tick the same night does not sweep again.
- **Test:** a room occupied for the whole window gives no sweep. A vacant tick at 05:00 or later gives no sweep.
- **Test:** a held manual-on light is not turned off.
- **Test:** there is no double fire across midnight, keyed by the window's start date.
- **Test:** the flash fires only when occupied. Vacant at 22:55 means no flash.
- **Test:** the zone sweep and vacancy exit still honour leave-on (regression).
- **Live:**
  - the next night, a `shared_space_auto_off` activity row for the Kitchen at the first vacant time after 23:00;
  - the Kitchen overhead off by morning;
  - no URA ERROR.
